# Usage:
#   .\scripts\dev-login.ps1 signup   (create a Supabase account)
#   .\scripts\dev-login.ps1 me       (sign in and call GET /api/v1/auth/me)
param([ValidateSet("signup", "me")][string]$Action = "me")

$ErrorActionPreference = "Stop"

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

$email = Read-Host "Email"
$secure = Read-Host "Password" -AsSecureString
$password = [System.Net.NetworkCredential]::new("", $secure).Password
$body = @{ email = $email; password = $password } | ConvertTo-Json
$headers = @{ apikey = $key }

if ($Action -eq "signup") {
    Invoke-RestMethod -Method Post -Uri "$url/auth/v1/signup" -Headers $headers -ContentType "application/json" -Body $body | Out-Null
    Write-Host "Sign-up sent. Confirm the email Supabase sends you, then run: .\scripts\dev-login.ps1 me"
    return
}

$session = Invoke-RestMethod -Method Post -Uri "$url/auth/v1/token?grant_type=password" -Headers $headers -ContentType "application/json" -Body $body
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/me" -Headers @{ Authorization = "Bearer $($session.access_token)" }