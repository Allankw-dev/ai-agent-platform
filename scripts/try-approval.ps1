# Usage (from the repo root, with the stack running):
#   .\scripts\try-approval.ps1                       # asks you to approve or reject
#   .\scripts\try-approval.ps1 -Decision approve     # approves without asking
#   .\scripts\try-approval.ps1 -Decision reject -Note "Use a spreadsheet instead"
#
# Shows the approval flow end to end without the approval screens (those come later):
#   1. signs in to Supabase,
#   2. creates a small agent whose calculator tool needs a person's approval,
#   3. starts a run and waits until it pauses ("awaiting_approval"),
#   4. shows you the pending request exactly as an approver sees it,
#   5. approves or rejects it, and waits for the run to finish,
#   6. tries to decide the same approval again, which must be refused.
# You must be an owner or admin of your organization to decide. Creates one new agent per run.
param(
    [ValidateSet("ask", "approve", "reject")]
    [string]$Decision = "ask",
    [string]$Note = "",
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

function Show-Steps($detail) {
    Write-Host "Steps:"
    foreach ($step in $detail.steps) {
        $label = if ($step.tool_key) { "$($step.step_type) $($step.tool_key)" } else { $step.step_type }
        $note = if ($step.error) { " - $($step.error)" } else { "" }
        Write-Host ("  {0}. {1} [{2}]{3}" -f $step.sequence, $label, $step.status, $note)
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
    throw "You are not in any organization yet. Create one at http://localhost:$webPort/orgs/new first."
}
$org = $orgs.items[0]
if ($org.role -notin @("owner", "admin")) {
    throw "Your role in '$($org.name)' is '$($org.role)'. Only an owner or admin can approve actions."
}
Write-Host "2. Organization: $($org.name) (you are $($org.role))." -ForegroundColor Green

# --- 3. an agent whose calculator needs approval ---
$agentBody = @{
    name   = "Approval demo " + (Get-Date -Format "HHmmss")
    config = @{
        provider            = "gemini"
        model               = $Model
        system_instructions = "You are a helpful assistant. Use the calculator tool for any arithmetic, then state the result."
        tools               = @(@{ tool_key = "utility.calculate"; requires_approval = $true })
    }
}
$agent = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents" -Body $agentBody
Write-Host "3. Agent created: $($agent.name). Its calculator needs approval." -ForegroundColor Green

# --- 4. run it and wait for the pause ---
$run = Invoke-Api -Method Post -Path "/organizations/$($org.id)/agents/$($agent.id)/runs" `
    -Body @{ message = $Message }
Write-Host "4. Run started. Asking: $Message" -ForegroundColor Green
$detail = $null
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    $detail = Invoke-Api -Method Get -Path "/organizations/$($org.id)/runs/$($run.id)"
    Write-Host "   ... $($detail.status)"
    if ($detail.status -notin @("queued", "running")) { break }
}
if ($detail.status -ne "awaiting_approval") {
    Write-Host ""
    Write-Host "The run did not pause for approval (status: $($detail.status))." -ForegroundColor Yellow
    if ($detail.error) { Write-Host "Error: $($detail.error)" -ForegroundColor Red }
    Show-Steps $detail
    throw "Nothing to approve."
}

# --- 5. show the request as an approver sees it ---
$pending = Invoke-Api -Method Get `
    -Path "/organizations/$($org.id)/approvals?status=pending&run_id=$($run.id)"
$approval = $pending.items[0]
Write-Host ""
Write-Host "=== WAITING FOR YOUR DECISION ===" -ForegroundColor Cyan
Write-Host "Agent   : $($approval.agent_name) (version $($approval.agent_version))"
Write-Host "Action  : $($approval.tool_name) [$($approval.tool_key)]"
Write-Host "Exact input that will run if you approve:"
Write-Host ("  " + ($approval.proposed_input | ConvertTo-Json -Compress))
if ($approval.reasoning_summary) { Write-Host "The agent said: $($approval.reasoning_summary)" }
Write-Host "Expires in $([math]::Round($approval.seconds_left / 3600, 1)) hours."
Write-Host ""

$verb = $Decision
if ($verb -eq "ask") {
    $answer = Read-Host "Approve, reject, or leave it for later? (a / r / l)"
    switch ($answer.ToLower()) {
        "a" { $verb = "approve" }
        "r" { $verb = "reject" }
        default {
            Write-Host "Left waiting. Approval id: $($approval.id)" -ForegroundColor Yellow
            Write-Host "Decide later with: POST $api/organizations/$($org.id)/approvals/$($approval.id)/approve (or /reject)"
            return
        }
    }
}

$body = if ($Note) { @{ note = $Note } } else { $null }
$decided = Invoke-Api -Method Post -Path "/organizations/$($org.id)/approvals/$($approval.id)/$verb" -Body $body
Write-Host "5. Decision recorded: $($decided.status) by $($decided.decided_by_name)." -ForegroundColor Green

# --- 6. wait for the run to carry on and finish ---
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    $detail = Invoke-Api -Method Get -Path "/organizations/$($org.id)/runs/$($run.id)"
    Write-Host "   ... $($detail.status)"
    if ($detail.status -notin @("queued", "running", "awaiting_approval")) { break }
}
Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Write-Host "Status : $($detail.status)"
if ($detail.error) { Write-Host "Error  : $($detail.error)" -ForegroundColor Red }
if ($detail.output) { Write-Host "Answer : $($detail.output.text)" }
Write-Host ""
Show-Steps $detail

# --- 7. deciding twice must be refused ---
Write-Host ""
Write-Host "7. Trying to approve the same request again (it must be refused)..." -ForegroundColor Cyan
try {
    Invoke-Api -Method Post -Path "/organizations/$($org.id)/approvals/$($approval.id)/approve" | Out-Null
    Write-Host "UNEXPECTED: the second approval was accepted." -ForegroundColor Red
}
catch {
    Write-Host "(The refusal above is the expected result: an approval can be decided once.)" -ForegroundColor Green
}
