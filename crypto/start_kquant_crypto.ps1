param(
    [int]$Port = 8010,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = Join-Path (Split-Path -Parent $Root) ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}
$env:KQUANT_CRYPTO_PORT = [string]$Port

Push-Location $Root
try {
    Write-Host "Starting KQUANT Crypto on http://127.0.0.1:$Port/" -ForegroundColor Cyan
    & $Python -m kquant_crypto serve
} finally {
    Pop-Location
}
