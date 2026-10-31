function Get-FoundationProcessIdentity {
  param([int]$ProcessId)
  $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -OperationTimeoutSec 2 -ErrorAction Stop
  if (-not $process) { return $null }
  if (-not $process.CreationDate -or -not $process.ExecutablePath) {
    throw [UnauthorizedAccessException]::new('PROCESS_IDENTITY_FIELDS_UNAVAILABLE')
  }
  return [pscustomobject]@{ pid = [int]$process.ProcessId; created_at = $process.CreationDate.ToUniversalTime().ToString("o"); executable = [string]$process.ExecutablePath }
}

function Assert-FoundationMatchingIdentity {
  param($Expected, $Actual, [string]$Code = 'PROCESS_PID_IDENTITY_CHANGED')
  if (-not $Expected -or -not $Expected.created_at -or -not $Expected.executable -or
      -not $Actual -or -not $Actual.created_at -or -not $Actual.executable -or
      $Expected.pid -ne $Actual.pid -or $Expected.created_at -ne $Actual.created_at -or
      $Expected.executable -ne $Actual.executable) { throw $Code }
}

function Get-FoundationSystemBoot {
  try {
    $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 2 -ErrorAction Stop
    return [pscustomobject]@{ state = 'VERIFIED'; started_at = $os.LastBootUpTime.ToUniversalTime().ToString('o'); source = 'WIN32_OPERATING_SYSTEM' }
  } catch { return [pscustomobject]@{ state = 'UNAVAILABLE'; error_type = $_.Exception.GetType().Name } }
}

function Stop-FoundationOwnedServices {
  # Only a verified child or its currently verified descendants belong to this launch.
  $owned = @($script:OwnedListenerIdentities)
  foreach ($service in @($script:StartedServices)) {
    $expected = $service.identity
    $actual = Get-FoundationProcessIdentity $service.pid
    if (-not $actual) { continue }
    Assert-FoundationMatchingIdentity $expected $actual 'CLEANUP_PID_IDENTITY_CHANGED'
    $children = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = {0}" -f $service.pid) -OperationTimeoutSec 2 -ErrorAction Stop)
    foreach ($child in $children) { $owned += Get-FoundationProcessIdentity ([int]$child.ProcessId) }
    $owned += $expected
  }
  $seen = @{}
  foreach ($expected in $owned) {
    if (-not $expected -or $seen.ContainsKey([int]$expected.pid)) { continue }
    $seen[[int]$expected.pid] = $true
    $actual = Get-FoundationProcessIdentity ([int]$expected.pid)
    if (-not $actual) { continue }
    Assert-FoundationMatchingIdentity $expected $actual 'CLEANUP_PID_IDENTITY_CHANGED'
    Stop-Process -Id ([int]$expected.pid) -Force -ErrorAction Stop
  }
}

function Test-FoundationOwnedProcess {
  param([int]$ProcessId)
  $currentId = $ProcessId
  for ($depth = 0; $depth -lt 4 -and $currentId -gt 0; $depth++) {
    $current = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $currentId) -OperationTimeoutSec 2 -ErrorAction Stop
    if (-not $current) { return $false }
    if (-not $current.CreationDate -or -not $current.ExecutablePath) {
      throw [UnauthorizedAccessException]::new('PROCESS_IDENTITY_FIELDS_UNAVAILABLE')
    }
    foreach ($service in @($script:StartedServices)) {
      if ($currentId -eq $service.pid) {
        return $service.identity -and $current.CreationDate.ToUniversalTime().ToString('o') -eq $service.identity.created_at -and $current.ExecutablePath -eq $service.identity.executable
      }
    }
    $currentId = [int]$current.ParentProcessId
  }
  return $false
}

function Write-FoundationTerminalSnapshot {
  param([string]$State, [string]$Reason)
  # A rejected second launcher may log its failure, but must not replace the live manifest.
  if (-not $script:FoundationOwnsMutex -or -not $serviceManifest) { return }
  $value = [pscustomobject]@{ launcher_pid = [int]$PID; launcher_identity = $script:LauncherIdentity;
    run_session_id = $script:RunSessionId; system_boot = $script:SystemBoot; started_at = $script:LaunchStamp;
    checked_at = [DateTimeOffset]::UtcNow.ToString('o'); state = $State; exit_reason = $Reason;
    failed_stage = $script:FoundationStage; launches = @($script:StartedServices); listeners = @();
    health_verified = $false; recovery_count = $recoveryCount; backend_release = $env:KQUANT_BACKEND_RELEASE_ID;
    backend_manifest_sha256 = $env:KQUANT_BACKEND_MANIFEST_SHA256; research_health_is_separate = $true }
  try { Write-FoundationJson $serviceManifest $value }
  catch { Write-FoundationFailureFallback $State 'TERMINAL_SNAPSHOT_WRITE_FAILED' }
}

function Write-FoundationJson {
  param([Parameter(Mandatory=$true)][string]$Path, [Parameter(Mandatory=$true)]$Value)
  $temporary = "$Path.$PID.tmp"
  $serialized = $Value | ConvertTo-Json -Depth 6
  for ($attempt = 0; $attempt -lt 2; $attempt++) {
    try {
      [IO.File]::WriteAllText($temporary, $serialized, (New-Object Text.UTF8Encoding($false)))
      if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
      else { [IO.File]::Move($temporary, $Path) }
      return
    } catch {
      $exception = $_.Exception
      $isIo = $exception -is [IO.IOException] -or $exception.InnerException -is [IO.IOException]
      if (-not $isIo -or $attempt -eq 1) { throw }
      Start-Sleep -Milliseconds 200
    }
  }
}

function Write-FoundationFailureFallback {
  param([string]$State, [string]$Reason)
  # No exception message, credential, or new process enumeration in this fallback.
  $event = [pscustomobject]@{ observed_at = [DateTimeOffset]::UtcNow.ToString("o"); state = $State;
    reason = $Reason; launcher = $script:LauncherIdentity; backend_release = $env:KQUANT_BACKEND_RELEASE_ID;
    backend_manifest_sha256 = $env:KQUANT_BACKEND_MANIFEST_SHA256; health_verified = $false;
    stage = $script:FoundationStage; requested_release_id = $script:RequestedReleaseId; run_session_id = $script:RunSessionId; system_boot = $script:SystemBoot }
  [Console]::Error.WriteLine(($event | ConvertTo-Json -Depth 4 -Compress))
  try {
    $fallback = Join-Path $env:LOCALAPPDATA "KQUANT\runtime-incidents"
    [IO.Directory]::CreateDirectory($fallback) | Out-Null
    $target = Join-Path $fallback ("launcher-{0}.jsonl" -f $PID)
    [IO.File]::AppendAllText($target, (($event | ConvertTo-Json -Depth 4 -Compress) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
  } catch { [Console]::Error.WriteLine("LIFECYCLE_FALLBACK_UNAVAILABLE") }
}

function Write-FoundationLifecycle {
  param([string]$State, [string]$Reason = "", $Details = $null)
  if (-not $script:LaunchStamp) { return }
  $event = [pscustomobject]@{ observed_at = [DateTimeOffset]::UtcNow.ToString("o"); state = $State; reason = $Reason; launcher = $script:LauncherIdentity; backend_release = $env:KQUANT_BACKEND_RELEASE_ID; backend_manifest_sha256 = $env:KQUANT_BACKEND_MANIFEST_SHA256; stage = $script:FoundationStage; requested_release_id = $script:RequestedReleaseId; run_session_id = $script:RunSessionId; system_boot = $script:SystemBoot; details = $Details }
  try {
    if (-not $foundationRoot -or -not [IO.Path]::IsPathRooted($foundationRoot) -or -not [IO.Directory]::Exists($foundationRoot)) { throw 'FOUNDATION_RUNTIME_ROOT_REQUIRED' }
    $path = Join-Path $foundationRoot ("lifecycle.{0}.jsonl" -f $script:LaunchStamp)
    [IO.File]::AppendAllText($path, (($event | ConvertTo-Json -Depth 6 -Compress) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
  } catch {
    $cause = $_.Exception
    while ($cause.InnerException) { $cause = $cause.InnerException }
    Write-FoundationFailureFallback $State ("LIFECYCLE_WRITE_FAILED_" + $cause.GetType().Name + '_HRESULT_' + $cause.HResult)
  }
}


function Register-FoundationMonitorFailure {
  param($Failure)
  $cause = $Failure.Exception
  while ($cause.InnerException) { $cause = $cause.InnerException }
  $observationFailure = $cause -is [Microsoft.Management.Infrastructure.CimException] -or
    $cause.GetType().FullName -eq 'Microsoft.PowerShell.Cmdletization.Cim.CimJobException' -or
    $cause -is [UnauthorizedAccessException] -or
    ($cause -is [ComponentModel.Win32Exception] -and $cause.NativeErrorCode -eq 5)
  if ($script:FoundationStage -ne 'MAIN_LOOP' -or -not $observationFailure) { return $false }
  $details = [pscustomobject]@{
    code = 'PROCESS_OBSERVATION_UNAVAILABLE'
    error_type = $cause.GetType().Name
    hresult = $cause.HResult
    native_error_code = $(if ($cause.PSObject.Properties['NativeErrorCode']) { [string]$cause.NativeErrorCode })
    script_line = $Failure.InvocationInfo.ScriptLineNumber
    observation_state = 'UNKNOWN'
    recovery_permitted = $false
  }
  Write-FoundationTerminalSnapshot 'DEGRADED' 'PROCESS_OBSERVATION_UNAVAILABLE'
  Write-FoundationLifecycle 'DEGRADED' 'PROCESS_OBSERVATION_UNAVAILABLE' $details
  return $true
}

function Invoke-FoundationMonitorCycle {
  # Complete observation before recovery: an unknown sibling is not a proven exit.
  try {
    $exited = @()
    foreach ($service in @($script:StartedServices)) {
      $identity = Get-FoundationProcessIdentity $service.pid
      if ($identity) {
        Assert-FoundationMatchingIdentity $service.identity $identity
      } else { $exited += $service }
    }
    foreach ($service in $exited) {
      if ($script:recoveryCount -ge 3) { throw 'BOUNDED_RECOVERY_EXHAUSTED' }
      $servicePort = if ($service.name -eq 'stock-options-foundation') { 8001 } else { [int]$env:KQUANT_GATEWAY_PORT }
      if (@(Get-ListenerProcesses $servicePort).Count) { throw 'RECOVERY_LISTENER_ALREADY_PRESENT' }
      $script:FoundationStage = 'RECOVERY'
      $script:recoveryCount++
      Write-FoundationLifecycle 'RECOVERING' 'SERVICE_PROCESS_EXITED' ([pscustomobject]@{name=$service.name;identity=$service.identity;attempt=$script:recoveryCount})
      Start-Sleep -Seconds ([Math]::Min(30, 5 * $script:recoveryCount))
      $script:StartedServices = @($script:StartedServices | Where-Object { $_.pid -ne $service.pid })
      Start-KquantService $service.name $service.executable $service.arguments $service.working_directory
      Write-FoundationHeartbeat 'PROCESS_RESTARTED_AWAITING_HEALTH'
      $serviceHealthUrl = if ($servicePort -eq 8001) { 'http://127.0.0.1:8001/api/health/live' } else { $gatewayUrl }
      if (-not (Wait-Healthy $serviceHealthUrl)) { throw 'RECOVERY_HEALTH_UNVERIFIED' }
      $script:FoundationStage = 'MAIN_LOOP'
    }
    Write-FoundationHeartbeat 'RUNNING'
    return $true
  } catch {
    if (-not (Register-FoundationMonitorFailure $_)) { throw }
    return $false
  }
}

