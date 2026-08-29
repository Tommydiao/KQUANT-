param(
    [double]$SessionHours = 24,
    [int]$CooldownSeconds = 30,
    [int]$MaxSessions = 1,
    [int]$MaintenancePollSeconds = 60,
    [switch]$BinanceOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $Root "outputs"
$MarkerPath = Join-Path $OutputDir "crypto_collection_running.json"
$SupervisorLog = Join-Path $OutputDir "crypto_collection_watchdog.log"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $SupervisorLog -Value $line
    Write-Output $line
}

function Get-MaintenanceProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $command = [string]$_.CommandLine
            $command -match "finish_crypto_collection_maintenance\.ps1|rebuild_crypto_coverage_index\.py"
        }
}

function Wait-ForMaintenance {
    while ($true) {
        $active = @(Get-MaintenanceProcesses)
        if ($active.Count -eq 0) { return }
        Write-Log "Coverage maintenance is active; waiting before starting a collector session."
        Start-Sleep -Seconds ([Math]::Max(5, $MaintenancePollSeconds))
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if ($SessionHours -le 0) { throw "SessionHours must be positive." }
if ($CooldownSeconds -lt 0) { throw "CooldownSeconds cannot be negative." }
if ($MaxSessions -lt 0) { throw "MaxSessions cannot be negative; use 0 for continuous operation." }

# This is an opt-in process-scoped low-load profile. It never writes these
# values to .env and never enables credentials or private endpoints.
if ($BinanceOnly) {
    $env:KQUANT_CRYPTO_ENABLE_BINANCE = "true"
    $env:KQUANT_CRYPTO_ENABLE_OKX = "false"
    $env:KQUANT_CRYPTO_ENABLE_COINBASE = "false"
    $env:KQUANT_CRYPTO_ENABLE_KRAKEN = "false"
    $env:KQUANT_CRYPTO_HIGH_FREQUENCY_SYMBOLS = "BTCUSDT,ETHUSDT"
    $env:KQUANT_CRYPTO_STORAGE_FLUSH_EVERY = "10000"
}

Write-Log "Starting public market-data-only collection watchdog; hours=$SessionHours max_sessions=$MaxSessions binance_only=$BinanceOnly."
$sessionNumber = 0
while ($MaxSessions -eq 0 -or $sessionNumber -lt $MaxSessions) {
    Wait-ForMaintenance

    if (Test-Path -LiteralPath $MarkerPath) {
        try {
            $marker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
            $heartbeatValue = if ($marker.heartbeat_at) { $marker.heartbeat_at } else { $marker.started_at }
            $heartbeat = [DateTimeOffset]::Parse([string]$heartbeatValue)
            $age = (([DateTimeOffset]::UtcNow) - $heartbeat.ToUniversalTime()).TotalSeconds
            if ([string]$marker.status -eq "running" -and $age -le 180) {
                throw "an active collector session already exists"
            }
            Write-Log "Found a stale collector marker; the new session will replace it fail-closed."
        } catch {
            if ($_.Exception.Message -eq "an active collector session already exists") { throw }
            Write-Log "Existing collector marker is unreadable or stale; continuing fail-closed."
        }
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutPath = Join-Path $OutputDir "crypto_collection_$stamp.stdout.log"
    $stderrPath = Join-Path $OutputDir "crypto_collection_$stamp.stderr.log"
    Write-Log "Launching collector session $($sessionNumber + 1); stdout=$stdoutPath stderr=$stderrPath."
    $child = Start-Process -FilePath "python" `
        -ArgumentList @("-u", "scripts\run_crypto_collection.py", "--hours", "$SessionHours") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    $child.WaitForExit()
    $exitCode = $child.ExitCode
    $sessionNumber += 1
    Write-Log "Collector session $sessionNumber exited with code $exitCode. Maintenance remains fail-closed until it completes."

    Wait-ForMaintenance
    $maintenanceScript = Join-Path $Root "scripts\finish_crypto_collection_maintenance.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $maintenanceScript -PollSeconds $MaintenancePollSeconds
    $maintenanceExit = $LASTEXITCODE
    Write-Log "Coverage maintenance after session $sessionNumber exited with code $maintenanceExit."

    if ($MaxSessions -ne 0 -and $sessionNumber -ge $MaxSessions) { break }
    if ($CooldownSeconds -gt 0) {
        Write-Log "Waiting $CooldownSeconds seconds before the next session."
        Start-Sleep -Seconds $CooldownSeconds
    }
}

Write-Log "Collection watchdog finished after $sessionNumber session(s)."
