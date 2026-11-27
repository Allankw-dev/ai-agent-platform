# Usage (from the repo root, with the whole stack running, including the scheduler):
#   .\scripts\try-recovery.ps1
#
# Shows crash recovery (Phase 5C) with a real kill:
#   1. signs in and creates a small agent with a calculator tool,
#   2. starts a run and, as soon as a worker is busy with it, STOPS THE WORKER CONTAINER
#      (`docker compose kill worker`), as if the machine had died,
#   3. starts the worker again,
#   4. watches the run: within about a minute the scheduler notices the silence, takes the run over
#      (attempt 2) and a worker finishes it. Steps that had finished are not repeated.
# Needs docker compose on this machine and the `scheduler` service running. Creates one agent.
param(
    [string]$Message = "Work out 12 * 34, then 56 + 78, then add the two results. Use the calculator tool for each step.",
    [string]$Model = "gemini-3-flash-preview",
    [int]$WaitSeconds = 180
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



function Get-RunStatus($orgId, $runId) {
    Invoke-Api -Method Get -Path "/organizations/$orgId/runs/$runId"
}

# --- 1. sign in, create an agent ---
$email = Read-Host "Email"
$secure = Read-Host "Password" -AsSecureString
$password = [System.Net.NetworkCredential]::new("", $secure).Password
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
$session = Invoke-RestMethod -Method Post -Uri "$url/auth/v1/token?grant_type=password" `
    -Headers @{ apikey = $key } -ContentType "application/json" -Body $loginBody
$script:headers = @{ Authorization = "Bearer $($session.access_token)" }
$orgs = Invoke-Api -Method Get -Path "/organizations"
if ($orgs.items.Count -eq 0) {
    throw "You are not in any organization yet. Create one at http://localhost:$webPort/orgs/new first."
}
$org = $orgs.items[0]
if (-not (docker compose ps --status running --services | Select-String -Pattern "^scheduler$" -Quiet)) {
    throw "The scheduler service is not running. Start it with: docker compose up -d --build"
}
$agent = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents" -Body @{
    name   = "Recovery demo " + (Get-Date -Format "HHmmss")
    config = @{
        provider            = "gemini"
        model               = $Model
        system_instructions = "You are a careful assistant. Use the calculator tool for every calculation, one call at a time, then state the final result."
        tools               = @(@{ tool_key = "utility.calculate" })
    }
}
Write-Host "1. Signed in. Agent created: $($agent.name)." -ForegroundColor Green

# --- 2. start a run and kill the worker while it is busy ---
$run = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents/$($agent.id)/runs" -Body @{ message = $Message }
for ($i = 0; $i -lt 60; $i++) {
    $detail = Get-RunStatus $org.id $run.id
    if ($detail.status -eq "running") { break }
    Start-Sleep -Milliseconds 500
}
Start-Sleep -Seconds 2   # let it get into the first steps
Write-Host "2. The run is working ($($detail.steps.Count) step(s) so far). Killing the worker now..." -ForegroundColor Yellow
docker compose kill worker | Out-Null
$during = Get-RunStatus $org.id $run.id
Write-Host "   Worker stopped. The run still says: $($during.status) (nothing else is alive to change it)."

# --- 3. bring a worker back ---
Start-Sleep -Seconds 3
docker compose start worker | Out-Null
Write-Host "3. Worker started again." -ForegroundColor Green

# --- 4. watch the recovery ---
Write-Host "4. Waiting for the scheduler to notice and take the run over (about a minute)..." -ForegroundColor Green
$started = Get-Date
$lastLine = ""
while (((Get-Date) - $started).TotalSeconds -lt $WaitSeconds) {
    $detail = Get-RunStatus $org.id $run.id
    $line = "status={0} attempt={1} steps={2}" -f $detail.status, $detail.attempt, $detail.steps.Count
    if ($line -ne $lastLine) {
        Write-Host ("   {0,4:N0}s  {1}" -f ((Get-Date) - $started).TotalSeconds, $line)
        $lastLine = $line
    }
    if ($detail.status -in @("succeeded", "failed", "cancelled")) { break }
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Write-Host "Status  : $($detail.status)   (attempt $($detail.attempt))"
if ($detail.error) { Write-Host "Error   : $($detail.error)" -ForegroundColor Red }
if ($detail.output) { Write-Host "Answer  : $($detail.output.text)" }
Write-Host ""
Write-Host "Steps (a step cut short is marked failed and was run again; finished steps stay as they were):"
foreach ($step in $detail.steps) {
    Write-Host ("  {0,2}. {1,-10} {2,-9} {3}" -f $step.sequence, $step.step_type, $step.status, $step.tool_key)
}
if ($detail.attempt -gt 1) {
    Write-Host ""
    Write-Host "Recovered after the worker stopped, as designed." -ForegroundColor Green
}
