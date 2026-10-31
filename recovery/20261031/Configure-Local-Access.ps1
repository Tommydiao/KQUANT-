param([switch]$Replace)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$helper = Join-Path $PSScriptRoot 'source\development\workspace\scripts\configure_local_access.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $helper)) {
  throw 'Verified local Python and setup helper are required.'
}
foreach ($kind in @('login', 'market')) {
  $arguments = @($helper, '--kind', $kind)
  if ($Replace) { $arguments += '--replace' }
  & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw "Local $kind setup did not complete. No service was started." }
}
Write-Host 'Local encrypted setup completed. Production and signal publication remain disabled.'
