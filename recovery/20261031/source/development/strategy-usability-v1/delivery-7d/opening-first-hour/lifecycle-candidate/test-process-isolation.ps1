param([Parameter(Mandatory=$true)][string]$EvidenceRoot,
      [Parameter(Mandatory=$true)][string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/scripts/FoundationLifecycle.ps1"
$allowed = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'source\development\strategy-usability-v1\delivery-7d\weekend-20261031')) + '\'
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
if (-not $EvidenceRoot.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'TEST_EVIDENCE_ROOT_OUTSIDE_WEEKEND_SCOPE' }
for ($part=$EvidenceRoot; $part; $part=[IO.Path]::GetDirectoryName($part)) {
  $entry=Get-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
  if($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'TEST_REPARSE_REFUSED' }
}
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$foundationRoot=$EvidenceRoot
$serviceManifest=Join-Path $EvidenceRoot 'services.test-only.json'
$script:FoundationOwnsMutex=$true # No production mutex is acquired by this isolation entry.
$script:RunSessionId=[guid]::NewGuid().ToString()
$script:LaunchStamp=[DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$script:FoundationStage='MAIN_LOOP'
$script:LauncherIdentity=Get-FoundationProcessIdentity $PID
$script:SystemBoot=Get-FoundationSystemBoot
$script:RequestedReleaseId='TEST_ONLY_LIFECYCLE_ISOLATION'
$env:KQUANT_BACKEND_RELEASE_ID='TEST_ONLY_LIFECYCLE_ISOLATION'
$env:KQUANT_BACKEND_MANIFEST_SHA256=(Get-FileHash "$PSScriptRoot/scripts/FoundationLifecycle.ps1").Hash.ToLowerInvariant()
$script:recoveryCount=0
$script:OwnedListenerIdentities=@()
$script:StartedServices=@()
$checks=[Collections.Generic.List[object]]::new()
$created=[Collections.Generic.List[object]]::new()
$hostExe=(Get-Process -Id $PID).Path
$script:FaultMode=''
$script:FaultPid=0
function Assert-Test($Condition, [string]$Name) {
  if(-not $Condition){ throw "ACCEPTANCE_FAILED_$Name" }
  $checks.Add([pscustomobject]@{name=$Name;pass=$true;at=[DateTimeOffset]::UtcNow.ToString('o')})
}
function Start-TestChild([string]$Name, [switch]$Leaf) {
  $proof=Join-Path $EvidenceRoot "$Name.child.json"
  $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
    ('"'+"$PSScriptRoot/acceptance-child.ps1"+'"'),'-EvidencePath',('"'+$proof+'"'))
  if($Leaf){$args+='-Leaf'}
  $p=Start-Process -FilePath $hostExe -ArgumentList $args -WindowStyle Hidden -PassThru
  $identity=Get-FoundationProcessIdentity $p.Id
  $created.Add([pscustomobject]@{process=$p;identity=$identity})
  $limit=[DateTime]::UtcNow.AddSeconds(15)
  while(-not (Test-Path -LiteralPath $proof)) {
    if($p.HasExited -or [DateTime]::UtcNow -ge $limit){throw 'TEST_CHILD_START_FAILED'}
    Start-Sleep -Milliseconds 50
  }
  return [pscustomobject]@{name=$Name;pid=$p.Id;identity=$identity;proof=(Get-Content -LiteralPath $proof -Raw | ConvertFrom-Json)}
}
function Write-FoundationHeartbeat([string]$State) {
  # No HTTP or worker claim: this test-only sink uses the real JSON snapshot writer.
  foreach($service in $script:StartedServices) {
    Assert-FoundationMatchingIdentity $service.identity (Get-FoundationProcessIdentity $service.pid)
  }
  Write-FoundationTerminalSnapshot $State 'TEST_ONLY_PROCESS_OBSERVATION'
}
function Get-CimInstance {
  [CmdletBinding()] param([Parameter(Position=0)][string]$ClassName,[string]$Filter,[int]$OperationTimeoutSec=2)
  if($Filter -eq "ProcessId = $script:FaultPid" -and $script:FaultMode) {
    $mode=$script:FaultMode; $script:FaultMode=''
    if($mode -eq 'REAL_INVALID_NAMESPACE') {
      return CimCmdlets\Get-CimInstance -Namespace 'root\KQUANT_TEST_ONLY_MISSING' -ClassName $ClassName -OperationTimeoutSec 2 -ErrorAction Stop
    }
    if($mode -eq 'ACCESS_DENIED') { throw [UnauthorizedAccessException]::new('TEST_ONLY_ACCESS_DENIED') }
    if($mode -eq 'MISSING_EXECUTABLE') {
      $p=CimCmdlets\Get-CimInstance -ClassName $ClassName -Filter $Filter -OperationTimeoutSec 2 -ErrorAction Stop
      return [pscustomobject]@{ProcessId=$p.ProcessId;CreationDate=$p.CreationDate;ExecutablePath=$null}
    }
  }
  return CimCmdlets\Get-CimInstance -ClassName $ClassName -Filter $Filter -OperationTimeoutSec $OperationTimeoutSec -ErrorAction Stop
}
$failure=$null
try {
  $tokens=$null;$parseErrors=$null
  [Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot/start_kquant_workspace.ps1",[ref]$tokens,[ref]$parseErrors) | Out-Null
  Assert-Test ($parseErrors.Count -eq 0) 'ACTUAL_HOST_PARSE'
  $originalHostCheck=& $hostExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot 'Start-Local-KQUANT.ps1') -HostCheckOnly
  Assert-Test ($LASTEXITCODE -eq 0 -and ($originalHostCheck | ConvertFrom-Json).ready) 'ORIGINAL_ENTRY_HOST_CHECK_ONLY'
  [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'original-host-check.json'),($originalHostCheck -join "`n"),[Text.UTF8Encoding]::new($false))
  $negativeRoot=Join-Path $EvidenceRoot 'preflight-reject-data'
  $negativeArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
    ('"'+"$PSScriptRoot/start_kquant_workspace.ps1"+'"'),'-OptionsFoundation','-NoBrowser',
    '-RuntimeRoot',('"'+$negativeRoot+'"'),'-PythonExecutable',('"'+(Join-Path $ProjectRoot '.venv\Scripts\python.exe')+'"'))
  $negative=Start-Process -FilePath $hostExe -ArgumentList $negativeArgs -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $EvidenceRoot 'entry-rejection.stdout.log') `
    -RedirectStandardError (Join-Path $EvidenceRoot 'entry-rejection.stderr.log')
  $negativeIdentity=Get-FoundationProcessIdentity $negative.Id
  $created.Add([pscustomobject]@{process=$negative;identity=$negativeIdentity})
  if(-not $negative.WaitForExit(15000)){throw 'NEGATIVE_ENTRY_TIMEOUT'}
  Assert-Test ($negative.ExitCode -ne 0) 'ACTUAL_CANDIDATE_ENTRY_REJECTS_MISSING_RECOVERY_GATE'
  $negativeLogs=@(Get-ChildItem -LiteralPath (Join-Path $negativeRoot 'work\option_foundation\runtime') -Filter '*.jsonl')
  $negativeEvents=@($negativeLogs | ForEach-Object {Get-Content -LiteralPath $_.FullName | ForEach-Object {$_ | ConvertFrom-Json}})
  Assert-Test ([bool]($negativeEvents | Where-Object {$_.state -eq 'FAILED' -and $_.stage -eq 'PREFLIGHT' -and $_.details.code -eq 'EXPLICIT_RUNTIME_REQUIRES_RECOVERY_GATE'})) 'PREFLIGHT_FAILURE_SAVED_IN_DATAROOT'
  Assert-Test (-not ($negativeEvents | Where-Object {$_.state -in @('SERVICE_STARTED','STARTING','RUNNING')})) 'ENTRY_REJECTION_NO_SERVICE_STARTED'
  Assert-Test (@(Get-ChildItem -LiteralPath $negativeRoot -Recurse -File | Where-Object {$_.Extension -in @('.sqlite3','.sqlite','.db')}).Count -eq 0) 'ENTRY_REJECTION_NO_DATABASE_CREATED'

  $owner=Start-TestChild 'owned-parent'
  $outsider=Start-TestChild 'unrelated' -Leaf
  $script:StartedServices=@($owner)
  $childId=[int]$owner.proof.child_pid
  $childIdentity=Get-FoundationProcessIdentity $childId
  $created.Add([pscustomobject]@{process=(Get-Process -Id $childId);identity=$childIdentity})
  Assert-Test (Test-FoundationOwnedProcess $owner.pid) 'ACTUAL_OWNER_IDENTITY'
  Assert-Test (Test-FoundationOwnedProcess $childId) 'ACTUAL_DESCENDANT_OWNERSHIP'
  Assert-Test (-not (Test-FoundationOwnedProcess $outsider.pid)) 'UNRELATED_PROCESS_NOT_OWNED'
  Assert-Test (Invoke-FoundationMonitorCycle) 'ACTUAL_HEALTHY_MONITOR_CYCLE'
  foreach($mode in @('REAL_INVALID_NAMESPACE','ACCESS_DENIED','MISSING_EXECUTABLE')) {
    $script:FaultPid=$owner.pid;$script:FaultMode=$mode
    Assert-Test (-not (Invoke-FoundationMonitorCycle)) $mode
    $snapshot=Get-Content -LiteralPath $serviceManifest -Raw | ConvertFrom-Json
    Assert-Test ($snapshot.state -eq 'DEGRADED' -and -not $snapshot.health_verified -and $snapshot.recovery_count -eq 0) ($mode+'_UNKNOWN_NO_RECOVERY')
    Assert-Test ([bool](Get-FoundationProcessIdentity $owner.pid)) ($mode+'_OWNER_SURVIVED')
    Assert-Test (Invoke-FoundationMonitorCycle) ($mode+'_OBSERVATION_RECOVERS')
  }
  $saved=$owner.identity
  $owner.identity=[pscustomobject]@{pid=$saved.pid;created_at='2000-01-01T00:00:00Z';executable=$saved.executable}
  $rejected=$false
  try { Stop-FoundationOwnedServices } catch { $rejected=$_.Exception.Message -eq 'CLEANUP_PID_IDENTITY_CHANGED' }
  Assert-Test $rejected 'PID_REUSE_IDENTITY_REJECTED'
  Assert-Test ([bool](Get-FoundationProcessIdentity $owner.pid)) 'MISMATCH_CLEANUP_PRESERVES_PROCESS'
  $owner.identity=$saved
  $script:FaultMode='ACCESS_DENIED';$script:FaultPid=$owner.pid
  $rejected=$false
  try { Stop-FoundationOwnedServices } catch { $rejected=$_.Exception -is [UnauthorizedAccessException] }
  Assert-Test $rejected 'CLEANUP_ACCESS_UNKNOWN_REFUSED'
  Assert-Test ([bool](Get-FoundationProcessIdentity $owner.pid)) 'ACCESS_UNKNOWN_PRESERVES_PROCESS'

  $exited=Start-TestChild 'confirmed-exit' -Leaf
  Assert-FoundationMatchingIdentity $exited.identity (Get-FoundationProcessIdentity $exited.pid)
  Stop-Process -Id $exited.pid -Force
  (Get-Process -Id $exited.pid -ErrorAction SilentlyContinue) | Wait-Process -Timeout 5 -ErrorAction SilentlyContinue
  $script:StartedServices=@($exited,$owner)
  $script:FaultMode='REAL_INVALID_NAMESPACE';$script:FaultPid=$owner.pid
  Assert-Test (-not (Invoke-FoundationMonitorCycle)) 'OBSERVE_ALL_BEFORE_RECOVERY'
  Assert-Test ($script:recoveryCount -eq 0) 'UNKNOWN_SIBLING_NO_PARTIAL_RECOVERY'
  $script:StartedServices=@($exited)
  $script:recoveryCount=3
  $rejected=$false
  try { Invoke-FoundationMonitorCycle | Out-Null } catch { $rejected=$_.Exception.Message -eq 'BOUNDED_RECOVERY_EXHAUSTED' }
  Assert-Test $rejected 'ACTUAL_EXIT_RECOVERY_LIMIT_RETAINED'
  $script:StartedServices=@($owner)
  $script:recoveryCount=0
  Stop-FoundationOwnedServices
  Start-Sleep -Milliseconds 200
  Assert-Test (-not (Get-FoundationProcessIdentity $owner.pid)) 'OWNED_PARENT_CLEANED'
  Assert-Test (-not (Get-FoundationProcessIdentity $childId)) 'OWNED_DESCENDANT_CLEANED'
  Assert-Test ([bool](Get-FoundationProcessIdentity $outsider.pid)) 'UNRELATED_PROCESS_SURVIVED_CLEANUP'
  # Use the unmodified launcher function bodies, real sockets and real child exits.
  $entryAst=[Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot/start_kquant_workspace.ps1",[ref]$tokens,[ref]$parseErrors)
  foreach($functionName in @('Get-ListenerProcesses','Start-KquantService','Wait-Healthy')) {
    $definition=$entryAst.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName}, $true)
    if(-not $definition){throw 'ACTUAL_ENTRY_FUNCTION_MISSING'}
    . ([scriptblock]::Create($definition.Extent.Text))
  }
  $LogRoot=$EvidenceRoot
  $OptionsFoundation=$true
  $portLease=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
  $portLease.Start();$testPort=$portLease.LocalEndpoint.Port;$portLease.Stop()
  if($testPort -lt 49152){throw 'TEST_PORT_OUTSIDE_EPHEMERAL_RANGE'}
  $env:KQUANT_GATEWAY_PORT=[string]$testPort
  $gatewayUrl="http://127.0.0.1:$testPort/"
  $script:StartedServices=@()
  $python=Join-Path $ProjectRoot '.venv\Scripts\python.exe'
  $healthArgs='-u "'+"$PSScriptRoot/acceptance-health.py"+'" --port '+$testPort
  Start-KquantService 'gateway-options-foundation' $python $healthArgs $PSScriptRoot
  $originalHealth=$script:StartedServices[0]
  $created.Add([pscustomobject]@{process=(Get-Process -Id $originalHealth.pid);identity=$originalHealth.identity})
  Assert-Test (Wait-Healthy $gatewayUrl) 'ACTUAL_LAUNCHER_CHILD_HEALTH'
  $healthListeners=@(Get-ListenerProcesses $testPort)
  Assert-Test ($healthListeners.Count -eq 1 -and (Test-FoundationOwnedProcess $healthListeners[0].ProcessId)) 'ACTUAL_HEALTH_LISTENER_OWNERSHIP'
  $script:OwnedListenerIdentities=@(Get-FoundationProcessIdentity $healthListeners[0].ProcessId)
  foreach($i in $script:OwnedListenerIdentities) {$created.Add([pscustomobject]@{process=(Get-Process -Id $i.pid);identity=$i})}
  Stop-FoundationOwnedServices
  Start-Sleep -Milliseconds 200
  $script:FoundationStage='MAIN_LOOP'
  Assert-Test (Invoke-FoundationMonitorCycle) 'ACTUAL_CHILD_EXIT_RESTART_AND_HEALTH'
  $replacement=$script:StartedServices[0]
  $created.Add([pscustomobject]@{process=(Get-Process -Id $replacement.pid);identity=$replacement.identity})
  Assert-Test ($script:recoveryCount -eq 1 -and $replacement.identity.created_at -ne $originalHealth.identity.created_at) 'RECOVERY_HAS_NEW_PROCESS_IDENTITY'
  $healthListeners=@(Get-ListenerProcesses $testPort)
  Assert-Test ($healthListeners.Count -eq 1 -and (Test-FoundationOwnedProcess $healthListeners[0].ProcessId)) 'RESTARTED_LISTENER_OWNED'
  $script:OwnedListenerIdentities=@(Get-FoundationProcessIdentity $healthListeners[0].ProcessId)
  foreach($i in $script:OwnedListenerIdentities) {$created.Add([pscustomobject]@{process=(Get-Process -Id $i.pid);identity=$i})}
  Stop-FoundationOwnedServices
  Start-Sleep -Milliseconds 200
  Assert-Test (@(Get-ListenerProcesses $testPort).Count -eq 0) 'ISOLATED_LISTENER_CLEANED'
} catch { $failure=[pscustomobject]@{type=$_.Exception.GetType().Name;message=$_.Exception.Message;line=$_.InvocationInfo.ScriptLineNumber} }
finally {
  $script:FaultMode=''
  foreach($item in $created) {
    $actual=Get-FoundationProcessIdentity $item.identity.pid
    if($actual) {
      Assert-FoundationMatchingIdentity $item.identity $actual 'TEST_CLEANUP_IDENTITY_CHANGED'
      Stop-Process -Id $item.identity.pid -Force -ErrorAction Stop
    }
  }
  Start-Sleep -Milliseconds 200
  $remaining=@($created | Where-Object {Get-FoundationProcessIdentity $_.identity.pid})
  $result=[ordered]@{schema='WEEKEND_C_LIFECYCLE_ISOLATION_V1';test_only=$true;observed_at=[DateTimeOffset]::UtcNow.ToString('o');
    host=$hostExe;ps_version=$PSVersionTable.PSVersion.ToString();checks=@($checks.ToArray());failure=$failure;
    process_identities=@($created | ForEach-Object {$_.identity});remaining_test_children=$remaining.Count;
    pass=(-not $failure -and $remaining.Count -eq 0);production_launch=$false;database_access=$false;
    fault_boundary='Real CIM invalid-namespace error; explicit access-denied/missing-field injection. No OS ACL or WMI service changes.';
    scope='Original HostCheckOnly entry, candidate File entry gate rejection, actual entry start/listener/health functions, shared monitor, real child recovery/ownership/cleanup. TEST_ONLY loopback health transport. Not successful production recovery gates, business HTTP, Worker or full topology acceptance.'}
  Write-FoundationJson (Join-Path $EvidenceRoot 'result.json') $result
  $result | ConvertTo-Json -Depth 7
}
if($failure -or $remaining.Count) { exit 1 }
