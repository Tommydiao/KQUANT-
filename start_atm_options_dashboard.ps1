param(
    [int]$Port = 8001,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv-win\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $ProjectRoot

Write-Host "Starting kquant ATM Options Signal Assistant..."
Write-Host "Dashboard: http://$HostName`:$Port/"
Write-Host "Fixture demo: http://$HostName`:$Port/?optionsSource=fixture"
Write-Host "Default: research-only signals. Alpaca Paper requires env keys plus manual confirmation; Live is disabled."

& $Python -m btc_eth_15m.dashboard.stdlib_server --host $HostName --port $Port
