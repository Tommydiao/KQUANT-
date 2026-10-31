param(
  [Parameter(Mandatory=$true)][string]$EntryScript,
  [Parameter(Mandatory=$true)][string]$RuntimeRoot,
  [Parameter(Mandatory=$true)][string]$ExpectedEntrySHA256
)
$ErrorActionPreference = 'Stop'
$logs = Join-Path $RuntimeRoot 'work\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$log = Join-Path $logs ('detached.{0}.{1}.log' -f $stamp,$PID)
try {
  if ((Get-FileHash -LiteralPath $EntryScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedEntrySHA256) { throw 'DETACHED_ENTRY_CHANGED_BEFORE_START' }
  & $EntryScript -Start -Foreground *> $log
  if ($LASTEXITCODE -ne 0) { throw 'DETACHED_ENTRY_NONZERO_EXIT' }
} catch {
  # Exceptions may contain local credential details: retain the class, not text.
  $event = [pscustomobject]@{ observed_at=[DateTimeOffset]::UtcNow.ToString('o'); state='DETACHED_LAUNCH_FAILED'; pid=[int]$PID; error_type=$_.Exception.GetType().Name; script_line=$_.InvocationInfo.ScriptLineNumber; entry=$EntryScript; entry_sha256=$ExpectedEntrySHA256; runtime_root=$RuntimeRoot }
  [IO.File]::AppendAllText($log, (($event | ConvertTo-Json -Compress) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
  exit 1
}
