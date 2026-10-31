param([Parameter(Mandatory=$true)][string]$RuntimeRoot, [Parameter(Mandatory=$true)][string]$ExpectedCandidate)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'FoundationLifecycle.ps1')
$path = Join-Path $RuntimeRoot 'work\option_foundation\runtime\services.json'
$value = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($value.backend_release -ne $ExpectedCandidate) { throw 'STOP_CANDIDATE_MISMATCH' }
$expected = $value.launcher_identity
$actual = Get-FoundationProcessIdentity ([int]$expected.pid)
if ($actual) {
  if ($actual.created_at -ne $expected.created_at -or $actual.executable -ne $expected.executable) { throw 'STOP_LAUNCHER_IDENTITY_CHANGED' }
  Stop-Process -Id ([int]$expected.pid) -Force -ErrorAction Stop
}
$script:StartedServices = @($value.launches)
$script:OwnedListenerIdentities = @($value.listeners | Where-Object command_verified | ForEach-Object { $_.identity })
Stop-FoundationOwnedServices
$value.state = 'STOPPED'
$value.exit_reason = 'EXPLICIT_USER_STOP'
$value.checked_at = [DateTimeOffset]::UtcNow.ToString('o')
$value.health_verified = $false
$value.listeners = @()
Write-FoundationJson $path $value
[pscustomobject]@{ state='STOPPED'; candidate=$ExpectedCandidate; reason='EXPLICIT_USER_STOP'; business_data_modified=$false } | ConvertTo-Json
