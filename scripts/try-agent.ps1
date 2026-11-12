# Usage (from the repo root, with the stack running):
#   .\scripts\try-agent.ps1
#   .\scripts\try-agent.ps1 -Message "What is 15% of 2400?" -Model "gemini-flash-latest"
#
# Signs in to Supabase, creates a small agent with the calculator tool, runs it once, waits for the
# result and prints it with every step. Creates one new agent each time you run it.
param(
    [string]$Message = "What is (1200 * 0.16) + 45?",
    [string]$Model = "gemini-flash-latest"
)

$ErrorActionPreference = "Stop"
$api = "http://localhost:8000/api/v1"

# --- read .env (same approach as dev-login.ps1) ---
$envFile = Join-Path $PSScriptRoot "..\.env"
$settings = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') {
        $settings[$matches[1]] = $matches[2].Trim('"')
    }
}
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
$script:headers = @{ Authorization = "Bearer $($session.access_token)" }
Write-Host "1. Signed in." -ForegroundColor Green

# --- 2. pick the organization ---
$orgs = Invoke-Api -Method Get -Path "/organizations"
if ($orgs.items.Count -eq 0) {
    throw "You are not in any organization yet. Create one at http://localhost:3000/orgs/new first."
}
$org = $orgs.items[0]
if ($org.role -eq "member") {
    throw "Your role in '$($org.name)' is 'member', which cannot create agents. Use an owner, admin or developer."
}
Write-Host "2. Organization: $($org.name) (you are $($org.role))." -ForegroundColor Green

# --- 3. create the agent ---
$agentBody = @{
    name   = "Math helper " + (Get-Date -Format "HHmmss")
    config = @{
        provider            = "gemini"
        model               = $Model
        system_instructions = "You are a helpful assistant. Use the calculator tool for any arithmetic."
        tools               = @(@{ tool_key = "utility.calculate" })
    }
}
$agent = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents" -Body $agentBody
Write-Host "3. Agent created: $($agent.name) (model $Model)." -ForegroundColor Green

# --- 4. start a run ---
$run = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents/$($agent.id)/runs" `
    -Body @{ message = $Message }
Write-Host "4. Run started (status: $($run.status)). Asking: $Message" -ForegroundColor Green

# --- 5. wait for it to finish ---
$detail = $null
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    $detail = Invoke-Api -Method Get -Path "/organizations/$($org.id)/runs/$($run.id)"
    Write-Host "   ... $($detail.status)"
    if ($detail.status -notin @("queued", "running")) { break }
}

Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Write-Host "Status : $($detail.status)"
if ($detail.error) { Write-Host "Error  : $($detail.error)" -ForegroundColor Red }
if ($detail.output) { Write-Host "Answer : $($detail.output.text)" }
Write-Host "Tokens : $($detail.input_tokens) in / $($detail.output_tokens) out"
Write-Host ""
Write-Host "Steps:"
foreach ($step in $detail.steps) {
    $label = if ($step.tool_key) { "$($step.step_type) $($step.tool_key)" } else { $step.step_type }
    $note = if ($step.error) { " - $($step.error)" } else { "" }
    Write-Host ("  {0}. {1} [{2}]{3}" -f $step.sequence, $label, $step.status, $note)
}
if ($detail.status -in @("queued", "running")) {
    Write-Host ""
    Write-Host "Still not finished after 90 seconds. Check: docker compose logs worker --tail 30" -ForegroundColor Yellow
}
