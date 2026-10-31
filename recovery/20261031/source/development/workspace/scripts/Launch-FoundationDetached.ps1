param(
  [Parameter(Mandatory=$true)][string]$EntryScript,
  [Parameter(Mandatory=$true)][string]$RuntimeRoot,
  [Parameter(Mandatory=$true)][string]$ExpectedEntrySHA256
)
$ErrorActionPreference = 'Stop'
$codeRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'FoundationLifecycle.ps1')
$projectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $codeRoot))
$expectedEntry = Join-Path $projectRoot 'Start-Local-KQUANT.ps1'
if ([IO.Path]::GetFullPath($EntryScript) -ne $expectedEntry -or [IO.Path]::GetFullPath($RuntimeRoot) -ne (Join-Path $projectRoot 'runtime')) { throw 'DETACHED_ENTRY_RUNTIME_BINDING_MISMATCH' }
foreach ($path in @($EntryScript, $RuntimeRoot)) {
  if ($path.Contains('"') -or $path -notmatch '^[CDE]:\\') { throw 'DETACHED_LOCAL_PATH_REQUIRED' }
  for ($part = [IO.Path]::GetFullPath($path); $part; $part = [IO.Path]::GetDirectoryName($part)) {
    $item = Get-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'DETACHED_REPARSE_PATH' }
  }
}
if ((Get-FileHash -LiteralPath $EntryScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedEntrySHA256) { throw 'DETACHED_ENTRY_CHANGED' }
$runner = Join-Path $PSScriptRoot 'Invoke-FoundationDetached.ps1'
$hostPath = (Get-Process -Id $PID).Path
$hostEvidence = & $hostPath -NoProfile -NonInteractive -File $EntryScript -HostCheckOnly
if ($LASTEXITCODE -ne 0 -or ($hostEvidence | ConvertFrom-Json).ready -ne $true) { throw 'DETACHED_HOST_CAPABILITY_UNAVAILABLE' }
$command = '"{0}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}" -EntryScript "{2}" -RuntimeRoot "{3}" -ExpectedEntrySHA256 "{4}"' -f $hostPath,$runner,$EntryScript,$RuntimeRoot,$ExpectedEntrySHA256
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}
# The existing launcher runs under the caller identity, outside the tool's job tree.
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$command;CurrentDirectory=$projectRoot;ProcessStartupInformation=$startup}
if ($result.ReturnValue -ne 0) { throw ('DETACHED_CREATE_FAILED_' + $result.ReturnValue) }
$process = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $result.ProcessId) -OperationTimeoutSec 2
$owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner
if ($owner.ReturnValue -ne 0 -or $owner.User -ne [Environment]::UserName) { throw 'DETACHED_OWNER_UNCONFIRMED' }
$record = [pscustomobject]@{ launcher_pid = [int]$result.ProcessId; launcher_identity = Get-FoundationProcessIdentity ([int]$result.ProcessId);
  system_boot = Get-FoundationSystemBoot; entry = $EntryScript; entry_sha256 = $ExpectedEntrySHA256;
  host = $hostPath; runtime_root = $RuntimeRoot; observed_at = [DateTimeOffset]::UtcNow.ToString('o');
  hidden = $true; system_task_created = $false; launch_requested = $true; health_verified = $false }
$logs = Join-Path $RuntimeRoot 'work\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Write-FoundationJson (Join-Path $logs ('detached-request-{0}.json' -f $result.ProcessId)) $record
$record | ConvertTo-Json -Depth 5
