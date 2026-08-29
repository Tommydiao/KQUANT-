param(
    [int]$PollSeconds = 60,
    [int]$CoverageBatchSize = 4096,
    [int]$CoverageWorkers = 4,
    [switch]$SkipQuarantine,
    [switch]$SkipPublicEvidence,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$SessionPath = Join-Path $Root "outputs\crypto_collection_running.json"
$ManifestPath = Join-Path $Root "work\coverage_scope_manifest.json"
$RunReportPath = Join-Path $Root "outputs\coverage_scope_run_latest.json"
$LogPath = Join-Path $Root "outputs\coverage_maintenance.log"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $LogPath -Value $line
    Write-Output $line
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
Write-Log "Waiting for the independent market-data-only collector to finish."

$staleAfterSeconds = [Math]::Max(180, $PollSeconds * 3)
while (Test-Path -LiteralPath $SessionPath) {
    try {
        $session = Get-Content -LiteralPath $SessionPath -Raw | ConvertFrom-Json
        if ([string]$session.status -ne "running") {
            break
        }
        $heartbeatValue = $session.heartbeat_at
        if (-not $heartbeatValue) { $heartbeatValue = $session.started_at }
        $heartbeat = [DateTimeOffset]::Parse([string]$heartbeatValue)
        $ageSeconds = (([DateTimeOffset]::UtcNow) - $heartbeat.ToUniversalTime()).TotalSeconds
        if ($ageSeconds -gt $staleAfterSeconds) {
            Write-Log "Collector heartbeat is stale (${ageSeconds}s); continuing fail-closed maintenance."
            break
        }
    } catch {
        Write-Log "Collector session file is unreadable; continuing fail-closed maintenance."
        break
    }
    Start-Sleep -Seconds ([Math]::Max(5, $PollSeconds))
}

Write-Log "Collector session ended; writing the deterministic coverage scope manifest."
Push-Location $Root
try {
    if (-not $SkipQuarantine) {
        Write-Log "Quarantining invalid raw Parquet files without deleting evidence."
        & python scripts/quarantine_invalid_parquet.py --from-fragments --output outputs\parquet_quarantine_latest.json
        if ($LASTEXITCODE -ne 0) { throw "Parquet quarantine failed with exit code $LASTEXITCODE" }
    }
    & python scripts/rebuild_crypto_coverage_index.py --write-scope-manifest $ManifestPath
    if ($LASTEXITCODE -ne 0) { throw "scope manifest failed with exit code $LASTEXITCODE" }

    for ($attempt = 1; $attempt -le 2; $attempt++) {
        Write-Log "Running resumable coverage scope fragments (attempt $attempt)."
        & python scripts/rebuild_crypto_coverage_index.py --run-scope-manifest $ManifestPath --resume --batch-size $CoverageBatchSize --parallel-workers $CoverageWorkers --report-path $RunReportPath
        if ($LASTEXITCODE -ne 0) { throw "scope fragment run failed with exit code $LASTEXITCODE" }

        Write-Log "Merging fragments and publishing only after every expected scope is complete (attempt $attempt)."
        $mergeOutput = (& python scripts/rebuild_crypto_coverage_index.py --merge-fragments --scope-manifest $ManifestPath --publish | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "coverage merge failed with exit code $LASTEXITCODE" }
        try {
            $merge = $mergeOutput | ConvertFrom-Json
        } catch {
            throw "coverage merge returned invalid JSON"
        }
        if ([bool]$merge.published) {
            Write-Log "Coverage maintenance completed and the main index was published."
            break
        }
        if ($attempt -eq 2) {
            throw "coverage merge remains incomplete; main index was not published"
        }
        Write-Log "Coverage merge is incomplete; isolating newly discovered invalid files before the final retry."
        & python scripts/quarantine_invalid_parquet.py --from-fragments --output outputs\parquet_quarantine_latest.json
        if ($LASTEXITCODE -ne 0) { throw "Parquet quarantine retry failed with exit code $LASTEXITCODE" }
    }

    if (-not $SkipPublicEvidence) {
        Write-Log "Collecting the registered public evidence set for the 999 plan."
        & python scripts/collect_999_public_evidence.py --report-path outputs\crypto_999_public_evidence_latest.json
        if ($LASTEXITCODE -gt 2) { throw "public evidence batch failed with exit code $LASTEXITCODE" }
        Write-Log "Public evidence batch finished; partial/data_caution results remain fail-closed."
    }

    if (-not $SkipValidation) {
        Write-Log "Running the locked crypto_roll_v1 validation replay."
        & python scripts/run_crypto_roll_validation.py --interval 1h --min-bars 220 --max-hold-bars 24 --bootstrap-iterations 1000
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Validation replay passed its configured Gate."
        } elseif ($LASTEXITCODE -eq 2) {
            Write-Log "Validation replay completed but remains NO_GO; no permission is changed."
        } else {
            throw "validation replay failed with exit code $LASTEXITCODE"
        }
    }
} catch {
    Write-Log "Coverage maintenance stopped fail-closed: $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
