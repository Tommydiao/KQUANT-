function Get-FoundationProcessIdentity {
  param([int]$ProcessId)
  $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -OperationTimeoutSec 2 -ErrorAction Stop
  if (-not $process) { return $null }
  return [pscustomobject]@{ pid = [int]$process.ProcessId; created_at = $process.CreationDate.ToUniversalTime().ToString("o"); executable = [string]$process.ExecutablePath }
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
    if ($actual.created_at -ne $expected.created_at -or $actual.executable -ne $expected.executable) { throw 'CLEANUP_PID_IDENTITY_CHANGED' }
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
    if ($actual.created_at -ne $expected.created_at -or $actual.executable -ne $expected.executable) { throw 'CLEANUP_PID_IDENTITY_CHANGED' }
    Stop-Process -Id ([int]$expected.pid) -Force -ErrorAction Stop
  }
}

function Test-FoundationOwnedProcess {
  param([int]$ProcessId)
  $currentId = $ProcessId
  for ($depth = 0; $depth -lt 4 -and $currentId -gt 0; $depth++) {
    $current = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $currentId) -OperationTimeoutSec 2 -ErrorAction Stop
    if (-not $current) { return $false }
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
