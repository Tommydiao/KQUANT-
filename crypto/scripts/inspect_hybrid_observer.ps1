param([Parameter(Mandatory=$true)][string]$LaunchReceipt)
$ErrorActionPreference = 'Stop'
$receiptPath = (Resolve-Path -LiteralPath $LaunchReceipt).Path
if ((Get-Item -LiteralPath $receiptPath).Length -gt 65536) { throw 'Receipt too large' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.execution_enabled -ne $false) { throw 'Research receipt required' }
$argsList = @($receipt.command)
$outputIndex = [Array]::IndexOf($argsList, '--output')
if ($outputIndex -lt 0 -or $outputIndex + 1 -ge $argsList.Count) { throw 'Missing run identity' }
$run = [string]$argsList[$outputIndex + 1]
if ($run -notmatch '^outputs/hybrid_regime_v1/[a-zA-Z0-9_-]+$') { throw 'Invalid run path' }
$root = (Resolve-Path -LiteralPath $receipt.cwd).Path
$statusPath = Join-Path $root "$run/status.json"
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$receipt.pid)"
$identity = $false
$children = @()
if ($null -ne $process) {
    $born = ([DateTimeOffset]$process.CreationDate.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0
    $identity = ([Math]::Abs($born - [double]$receipt.launch_local_epoch) -lt 3) -and
        ($process.ExecutablePath -eq $argsList[0]) -and
        ($process.CommandLine.Contains('scripts/run_hybrid_continuous_observer.py')) -and
        ($process.CommandLine.Contains($run))
    if ($identity) {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$([int]$receipt.pid)" | Where-Object {
            $childBorn = ([DateTimeOffset]$_.CreationDate.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0
            $_.Name -eq 'python.exe' -and $childBorn -ge $born -and
                $childBorn - $born -lt 5 -and
                $_.CommandLine.Contains('scripts/run_hybrid_continuous_observer.py') -and
                $_.CommandLine.Contains($run)
        })
    }
}
$status = $null
if (Test-Path -LiteralPath $statusPath) {
    if ((Get-Item -LiteralPath $statusPath).Length -gt 65536) { throw 'Status too large' }
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
}
[ordered]@{
    scope = 'READ_ONLY_LAUNCH_PROCESS_CHECK_NOT_DATA_GATE'
    observed_local_utc = [DateTime]::UtcNow.ToString('o')
    pid = [int]$receipt.pid
    process_present = ($null -ne $process)
    launch_identity_matched = [bool]$identity
    process_working_directory_verified = $false
    child_process_verified = ($children.Count -eq 1)
    matching_child_pids = @($children | ForEach-Object { [int]$_.ProcessId })
    recorded_state = $status.state
    heartbeat_local_utc = $status.heartbeat_local_utc
    elapsed_seconds = $status.elapsed_seconds
    qualified_quotes = $status.counts.valid_quote_consumed
    opportunities = $status.opportunities
    labels = $status.label_statuses
    uptime_gate_pass = $status.uptime_gate_pass
    execution_authorized = $false
} | ConvertTo-Json -Depth 5
