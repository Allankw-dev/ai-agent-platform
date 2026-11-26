# Usage (from the repo root, with the stack running):
#   .\scripts\try-limits.ps1
#
# Shows the organization limits of Phase 5B working:
#   1. signs in and uses your first organization,
#   2. remembers its current limits, then sets "2 runs at once",
#   3. starts four runs back to back: two are accepted, two are refused with a plain explanation,
#   4. shows today's usage (what the finished runs really used),
#   5. puts the limits back exactly as they were (even if something above fails).
# Creates one new agent per run and starts two real (small) Gemini runs.
param(
    [string]$Model = "gemini-3-flash-preview"
)

$ErrorActionPreference = "Stop"

# --- read .env (same approach as try-agent.ps1) ---
$envFile = Join-Path $PSScriptRoot "..\.env"
$settings = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') {
        $settings[$matches[1]] = $matches[2].Trim('"')
    }
}
$apiPort = if ($settings["API_PORT"]) { $settings["API_PORT"] } else { "8000" }
$webPort = if ($settings["WEB_PORT"]) { $settings["WEB_PORT"] } else { "3000" }
$api = "http://localhost:$apiPort/api/v1"

$url = $settings["NEXT_PUBLIC_SUPABASE_URL"]
$key = $settings["NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"]
if (-not $url -or -not $key) {
    throw "Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in .env first."
}
$url = $url.TrimEnd("/")

# Calls the API and, on an error, prints the server's explanation instead of a stack trace.
function Invoke-Api {
    param([string]$Method, [string]$Path, $Body = $null)
    $arguments = @{
        Method  = $Method
        Uri     = "$api$Path"
        Headers = $script:headers
    }
    if ($null -ne $Body) {
        $arguments["ContentType"] = "application/json"
        $arguments["Body"] = ($Body | ConvertTo-Json -Depth 8)
    }
    try {
        return Invoke-RestMethod @arguments
    }
    catch {
        $detail = $_.ErrorDetails.Message
        if (-not $detail) { $detail = $_.Exception.Message }
        Write-Host ""
        Write-Host "The API returned an error for $Method $Path :" -ForegroundColor Red
        Write-Host $detail -ForegroundColor Red
        throw "Stopped."
    }
}



# Like Invoke-Api, but reports a refusal as data so the script can show it and carry on.
function Start-Run {
    param([string]$Path, $Body)
    try {
        $run = Invoke-RestMethod -Method Post -Uri "$api$Path" -Headers $script:headers `
            -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
        return @{ Accepted = $true; Run = $run }
    }
    catch {
        $detail = $_.ErrorDetails.Message
        $code = ""; $message = $detail
        try { $error1 = ($detail | ConvertFrom-Json).error; $code = $error1.code; $message = $error1.message } catch { }
        return @{ Accepted = $false; Code = $code; Message = $message }
    }
}

# --- 1. sign in ---
$email = Read-Host "Email"
$secure = Read-Host "Password" -AsSecureString
$password = [System.Net.NetworkCredential]::new("", $secure).Password
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
$session = Invoke-RestMethod -Method Post -Uri "$url/auth/v1/token?grant_type=password" `
    -Headers @{ apikey = $key } -ContentType "application/json" -Body $loginBody
$script:headers = @{ Authorization = "Bearer $($session.access_token)" }
Write-Host "1. Signed in." -ForegroundColor Green

$orgs = Invoke-Api -Method Get -Path "/organizations"
if ($orgs.items.Count -eq 0) {
    throw "You are not in any organization yet. Create one at http://localhost:$webPort/orgs/new first."
}
$org = $orgs.items[0]
if ($org.role -ne "owner" -and $org.role -ne "admin") {
    throw "Only an owner or admin can change limits. Your role in $($org.name) is $($org.role)."
}

# --- 2. remember the limits, then tighten them ---
$before = Invoke-Api -Method Get -Path "/organizations/$($org.id)/limits"
Write-Host ("2. {0}: {1} runs at once, {2} tokens a day ({3})." -f $org.name, `
    $before.max_concurrent_runs, $before.daily_token_quota, `
    $(if ($before.customized) { "your own limits" } else { "platform defaults" }))

try {
    $tight = @{
        max_concurrent_runs  = 2
        daily_token_quota    = $before.daily_token_quota
        daily_cost_quota_usd = $before.daily_cost_quota_usd
    }
    Invoke-Api -Method Put -Path "/organizations/$($org.id)/limits" -Body $tight | Out-Null
    Write-Host "   Limits set to 2 runs at once (restored at the end)." -ForegroundColor Yellow

    $agentBody = @{
        name   = "Limits demo " + (Get-Date -Format "HHmmss")
        config = @{
            provider            = "gemini"
            model               = $Model
            system_instructions = "You are a helpful assistant. Use the calculator tool for any arithmetic, then state the result."
            tools               = @(@{ tool_key = "utility.calculate" })
        }
    }
    $agent = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents" -Body $agentBody

    # --- 3. four runs, back to back ---
    Write-Host ""
    Write-Host "3. Starting four runs back to back:" -ForegroundColor Green
    $accepted = @()
    foreach ($n in 1..4) {
        $result = Start-Run -Path "/organizations/$($org.id)/agents/$($agent.id)/runs" `
            -Body @{ message = "What is $n * 7? Use the calculator tool." }
        if ($result.Accepted) {
            $accepted += $result.Run
            Write-Host "   run $n : accepted ($($result.Run.id))" -ForegroundColor Green
        }
        else {
            Write-Host "   run $n : refused ($($result.Code))" -ForegroundColor Yellow
            Write-Host "            $($result.Message)"
        }
    }

    # --- 4. wait for the accepted runs, then show usage ---
    Write-Host ""
    Write-Host "4. Waiting for the accepted runs to finish..." -ForegroundColor Green
    foreach ($run in $accepted) {
        for ($i = 0; $i -lt 90; $i++) {
            $detail = Invoke-Api -Method Get -Path "/organizations/$($org.id)/runs/$($run.id)"
            if ($detail.status -in @("succeeded", "failed", "cancelled")) { break }
            Start-Sleep -Seconds 2
        }
        Write-Host "   $($run.id): $($detail.status)"
    }
    $usage = Invoke-Api -Method Get -Path "/organizations/$($org.id)/usage?days=1"
    Write-Host ""
    Write-Host "=== USAGE TODAY ===" -ForegroundColor Cyan
    Write-Host ("Tokens : {0} in, {1} out" -f $usage.today.input_tokens, $usage.today.output_tokens)
    Write-Host ("Cost   : {0}" -f $usage.today.cost_usd)
    Write-Host ("Busy   : {0} run(s) queued or running right now" -f $usage.today.busy_runs)
}
finally {
    # --- 5. put the limits back exactly as they were ---
    if ($before.customized) {
        $restore = @{
            max_concurrent_runs  = $before.max_concurrent_runs
            daily_token_quota    = $before.daily_token_quota
            daily_cost_quota_usd = $before.daily_cost_quota_usd
        }
        Invoke-Api -Method Put -Path "/organizations/$($org.id)/limits" -Body $restore | Out-Null
    }
    else {
        Invoke-Api -Method Delete -Path "/organizations/$($org.id)/limits" | Out-Null
    }
    Write-Host ""
    Write-Host "5. Limits put back as they were." -ForegroundColor Green
}
