# Usage (from the repo root, with the stack running):
#   .\scripts\watch-run.ps1
#   .\scripts\watch-run.ps1 -Message "What is 123 * 45? Use the calculator tool."
#
# Shows a run's live event stream (Phase 5A) as it happens:
#   1. signs in to Supabase,
#   2. creates a small agent with a calculator tool (no approval needed),
#   3. starts a run and prints each event the moment the server sends it, with the seconds since
#      the start (keep-alive lines appear while nothing is happening),
#   4. then reconnects asking only for events after the second one, to show how a client that
#      lost its connection catches up without receiving anything twice.
# Needs curl.exe, which ships with Windows 10 and 11. Creates one new agent per run.
param(
    [string]$Message = "What is 7 * 6? Use the calculator tool.",
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


# --- 1. sign in ---
$email = Read-Host "Email"
$secure = Read-Host "Password" -AsSecureString
$password = [System.Net.NetworkCredential]::new("", $secure).Password
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
$session = Invoke-RestMethod -Method Post -Uri "$url/auth/v1/token?grant_type=password" `
    -Headers @{ apikey = $key } -ContentType "application/json" -Body $loginBody
$token = $session.access_token
$script:headers = @{ Authorization = "Bearer $token" }
Write-Host "1. Signed in." -ForegroundColor Green

# --- 2. pick the organization and create an agent ---
$orgs = Invoke-Api -Method Get -Path "/organizations"
if ($orgs.items.Count -eq 0) {
    throw "You are not in any organization yet. Create one at http://localhost:$webPort/orgs/new first."
}
$org = $orgs.items[0]
$agentBody = @{
    name   = "Stream demo " + (Get-Date -Format "HHmmss")
    config = @{
        provider            = "gemini"
        model               = $Model
        system_instructions = "You are a helpful assistant. Use the calculator tool for any arithmetic, then state the result."
        tools               = @(@{ tool_key = "utility.calculate" })
    }
}
$agent = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents" -Body $agentBody
Write-Host "2. Organization: $($org.name). Agent created: $($agent.name)." -ForegroundColor Green

# --- 3. start a run and watch its events live ---
$run = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents/$($agent.id)/runs" `
    -Body @{ message = $Message }
Write-Host "3. Run started. Events as they arrive:" -ForegroundColor Green
Write-Host ""
$streamUrl = "$api/organizations/$($org.id)/runs/$($run.id)/events/stream"
$started = Get-Date
& curl.exe -sN -H "Authorization: Bearer $token" $streamUrl | ForEach-Object {
    if ($_ -ne "") {
        $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        Write-Host ("{0,5}s  {1}" -f $seconds, $_)
    }
}

# --- 4. reconnect from the middle ---
Write-Host ""
Write-Host "4. Reconnecting with ?after=2 (what a client that dropped after event 2 would do):" -ForegroundColor Green
& curl.exe -sN -H "Authorization: Bearer $token" "$streamUrl`?after=2" | ForEach-Object {
    if ($_ -like "id:*" -or $_ -like "event:*") { Write-Host "       $_" }
}

$detail = Invoke-Api -Method Get -Path "/organizations/$($org.id)/runs/$($run.id)"
Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Write-Host "Status : $($detail.status)"
if ($detail.error) { Write-Host "Error  : $($detail.error)" -ForegroundColor Red }
if ($detail.output) { Write-Host "Answer : $($detail.output.text)" }
