param([switch]$Start, [switch]$Stop, [switch]$Foreground, [switch]$HostCheckOnly)
$ErrorActionPreference = 'Stop'
$RequiredCommands = @('Get-FileHash', 'Get-CimInstance', 'Get-NetTCPConnection', 'Start-Process')
$MissingCommands = @($RequiredCommands | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
$HostEvidence = [pscustomobject]@{
  executable = (Get-Process -Id $PID).Path
  version = $PSVersionTable.PSVersion.ToString()
  edition = $PSVersionTable.PSEdition
  missing_commands = $MissingCommands
  ready = $MissingCommands.Count -eq 0
}
if (-not $HostEvidence.ready) {
  [Console]::Error.WriteLine(($HostEvidence | ConvertTo-Json -Compress))
  throw 'POWERSHELL_HOST_CAPABILITY_PREFLIGHT_FAILED_NO_SERVICE_STARTED'
}
if ($HostCheckOnly) { $HostEvidence | ConvertTo-Json; exit 0 }
if ($Start -and $Stop) { throw 'CHOOSE_START_OR_STOP' }
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Code = Join-Path $Root 'source\development\workspace'
$EntryPath = Join-Path $Code 'config\local_workspace_entry.json'
$Entry = Get-Content -LiteralPath $EntryPath -Raw | ConvertFrom-Json
if ($Entry.code_root -ne $Code -or $Entry.runtime_root -ne (Join-Path $Root 'runtime') -or $Entry.python_executable -ne (Join-Path $Root '.venv\Scripts\python.exe')) { throw 'LOCAL_ENTRY_ROOT_MISMATCH' }
if ($Stop) {
  & (Join-Path $Code 'scripts\Stop-Foundation.ps1') -RuntimeRoot $Entry.runtime_root -ExpectedCandidate $Entry.candidate_id
  exit $LASTEXITCODE
}
foreach ($Proof in @($Entry.recovery_manifest, $Entry.runtime_manifest)) {
  $Full = [IO.Path]::GetFullPath($Proof.path)
  if (-not $Full.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'ENTRY_MANIFEST_OUTSIDE_ROOT' }
  for ($Part = $Full; $Part; $Part = [IO.Path]::GetDirectoryName($Part)) {
    $Item = Get-Item -LiteralPath $Part -Force -ErrorAction SilentlyContinue
    if ($Item -and ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'ENTRY_REPARSE_PATH' }
  }
  if ((Get-FileHash -LiteralPath $Full -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Proof.sha256) { throw 'ENTRY_MANIFEST_HASH_MISMATCH' }
}
$Roots = @($Root, $Entry.python_base_root)
if ($Start -and -not $Foreground) {
  & (Join-Path $Code 'scripts\Launch-FoundationDetached.ps1') -EntryScript $MyInvocation.MyCommand.Path -RuntimeRoot $Entry.runtime_root -ExpectedEntrySHA256 ((Get-FileHash -LiteralPath $MyInvocation.MyCommand.Path -Algorithm SHA256).Hash.ToLowerInvariant())
  exit $LASTEXITCODE
}
if (-not $Start) {
  & $Entry.python_executable -I -S (Join-Path $Code 'scripts\check_safe_recovery.py') --manifest $Entry.recovery_manifest.path --runtime-root $Entry.runtime_root --python-executable $Entry.python_executable --approved-local-root $Root --approved-local-root $Entry.python_base_root
  exit $LASTEXITCODE
}
& (Join-Path $Code 'start_kquant_workspace.ps1') -OptionsFoundation -OneMinuteShadow -NoBrowser -RuntimeRoot $Entry.runtime_root -PythonExecutable $Entry.python_executable -RecoveryLocalRoot $Roots -RecoveryManifest $Entry.recovery_manifest.path -RuntimeManifest $Entry.runtime_manifest.path -UnifiedWebDist $Entry.frontend
