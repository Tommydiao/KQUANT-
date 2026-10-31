$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/scripts/FoundationLifecycle.ps1"
$script:events = @()
function Write-FoundationTerminalSnapshot { param($State,$Reason); $script:events += "$State/$Reason" }
function Write-FoundationLifecycle { param($State,$Reason,$Details); $script:events += "$State/$Reason" }
$script:FoundationStage = 'MAIN_LOOP'
$exception = New-Object Microsoft.Management.Infrastructure.CimException 'TEST_ONLY'
$failure = [pscustomobject]@{ Exception=$exception; InvocationInfo=[pscustomobject]@{ScriptLineNumber=42} }
if (-not (Register-FoundationMonitorFailure $failure)) { throw 'CIM_NOT_HANDLED' }
if ($script:events.Count -ne 2 -or $script:events[0] -ne 'DEGRADED/PROCESS_OBSERVATION_UNAVAILABLE') { throw 'DEGRADED_NOT_RECORDED' }
function Get-CimInstance { throw (New-Object Microsoft.Management.Infrastructure.CimException 'TEST_ONLY_QUERY_CANCELLED') }
try {
  Test-FoundationOwnedProcess 24520 | Out-Null
  throw 'OWNERSHIP_QUERY_DID_NOT_FAIL'
} catch {
  if (-not (Register-FoundationMonitorFailure $_)) { throw }
}
if ($script:events.Count -ne 4) { throw 'OWNERSHIP_FAILURE_NOT_DEGRADED' }
$script:FoundationStage = 'RECOVERY'
if (Register-FoundationMonitorFailure $failure) { throw 'RECOVERY_FAILURE_SWALLOWED' }
$script:FoundationStage = 'MAIN_LOOP'
$failure.Exception = New-Object InvalidOperationException 'TEST_ONLY'
if (Register-FoundationMonitorFailure $failure) { throw 'NON_CIM_FAILURE_SWALLOWED' }
$tokens=$null; $errors=$null
[System.Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot/start_kquant_workspace.ps1",[ref]$tokens,[ref]$errors) | Out-Null
if ($errors.Count) { throw 'LAUNCHER_PARSE_FAILED' }
'PASS: CIM degradation, recovery/non-CIM propagation, Windows PowerShell parse; no services started.'
