param(
  [switch]$StartDashboard
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Read-SecretValue {
  param([string]$Prompt)
  $secure = Read-Host $Prompt -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    if ($bstr -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
  }
}

Write-Host "KQUANT Longbridge read-only market data setup" -ForegroundColor Cyan
Write-Host "This stores credentials in the current Windows user environment." -ForegroundColor DarkGray
Write-Host "KQUANT uses QuoteContext only. Account, position, trade, and order APIs remain disabled." -ForegroundColor DarkGray
Write-Host "Never paste credentials into GitHub, frontend variables, screenshots, or chat." -ForegroundColor Yellow
Write-Host "If credentials appeared in a screenshot, revoke them in Longbridge before continuing." -ForegroundColor Yellow
Write-Host ""

$appKey = Read-SecretValue "Paste new LONGBRIDGE_APP_KEY"
$appSecret = Read-SecretValue "Paste new LONGBRIDGE_APP_SECRET"
$accessToken = Read-SecretValue "Paste new LONGBRIDGE_ACCESS_TOKEN"

if (
  -not $appKey -or -not $appKey.Trim() -or
  -not $appSecret -or -not $appSecret.Trim() -or
  -not $accessToken -or -not $accessToken.Trim()
) {
  throw "One or more Longbridge values were empty. Nothing changed."
}

$settings = [ordered]@{
  LONGBRIDGE_APP_KEY = $appKey.Trim()
  LONGBRIDGE_APP_SECRET = $appSecret.Trim()
  LONGBRIDGE_ACCESS_TOKEN = $accessToken.Trim()
  KQUANT_MARKET_DATA_PROVIDER = "longbridge"
  LONGBRIDGE_PRINT_QUOTE_PACKAGES = "false"
}

foreach ($item in $settings.GetEnumerator()) {
  [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "User")
  [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "Process")
}

$appKey = $null
$appSecret = $null
$accessToken = $null

Write-Host ""
Write-Host "Saved Longbridge read-only market data configuration for this Windows user." -ForegroundColor Green
Write-Host "The values were not printed and were not written into the repository." -ForegroundColor DarkGray

if ($StartDashboard) {
  Write-Host "Starting KQUANT with Longbridge required..." -ForegroundColor Cyan
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "start_kquant_stock_terminal.ps1") -KillExisting -RequireLongbridge
} else {
  Write-Host "Next: run .\KQUANT_START.cmd" -ForegroundColor Green
}
