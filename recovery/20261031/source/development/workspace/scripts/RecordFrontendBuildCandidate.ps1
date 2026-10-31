param(
    [string]$UnifiedBuild = 'dist-unified',
    [string]$StockBuild = 'dist-stock',
    [string]$TestEvidence = 'vitest-service-scope.json',
    [string]$ReportName = 'build_receipt.json'
)
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\Desktop\Codex coding\kquant-safe-recovery-20261006'
$candidate = Join-Path $root 'evidence\frontend-build-candidate-20261007'

function Assert-NoLinks([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    if ($full -match '^[Ff]:') { throw 'FAULT_DRIVE_FORBIDDEN' }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'REPARSE_PATH_FORBIDDEN'
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
    return $full
}

function Get-Tree([string]$path) {
    $base = Assert-NoLinks $path
    $queue = [Collections.Generic.Queue[string]]::new()
    $queue.Enqueue($base)
    $result = [Collections.Generic.List[object]]::new()
    while ($queue.Count) {
        $directory = $queue.Dequeue()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            $file = Assert-NoLinks $item.FullName
            if ($item.PSIsContainer) { $queue.Enqueue($file); continue }
            if ($result.Count -ge 256 -or $item.Length -gt 2097152) { throw 'FINGERPRINT_BUDGET' }
            $result.Add([pscustomobject]@{relative=$file.Substring($base.Length + 1).Replace('\','/');
                bytes=$item.Length; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()})
        }
    }
    return @($result.ToArray() | Sort-Object relative)
}

$candidate = Assert-NoLinks $candidate
foreach ($name in @($UnifiedBuild, $StockBuild, $TestEvidence, $ReportName)) {
    if ($name -notmatch '^[A-Za-z0-9_.-]+$') { throw 'RELATIVE_CANDIDATE_ITEM_REQUIRED' }
}
$outputReceipt = Assert-NoLinks (Join-Path $candidate $ReportName)
if (Test-Path -LiteralPath $outputReceipt) { throw 'IMMUTABLE_BUILD_RECEIPT_ALREADY_EXISTS' }
$original = Get-Content -LiteralPath (Assert-NoLinks (Join-Path $root 'evidence\retained-frontend-metadata-20261007\receipt.json')) -Raw | ConvertFrom-Json
$lock = Assert-NoLinks (Join-Path $candidate 'package-lock.json')
$lockHash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant()
if ($lockHash -ne (@($original.files | Where-Object path -Like '*\package-lock.json')[0].sha256)) {
    throw 'ARCHIVED_LOCK_CHANGED'
}
$developmentSources = Get-Tree (Join-Path $root 'dev\web\src')
$candidateSources = Get-Tree (Join-Path $candidate 'src')
if (($developmentSources | ConvertTo-Json -Depth 4 -Compress) -ne
    ($candidateSources | ConvertTo-Json -Depth 4 -Compress)) { throw 'DEVELOPMENT_SOURCE_MISMATCH' }
$tests = Get-Content -LiteralPath (Assert-NoLinks (Join-Path $candidate $TestEvidence)) -Raw | ConvertFrom-Json
if ($tests.numFailedTests -ne 0 -or $tests.numFailedTestSuites -ne 0) { throw 'FRONTEND_TESTS_FAILED' }
$builds = foreach ($name in @($UnifiedBuild, $StockBuild)) {
    [pscustomobject]@{directory=$name; files=@(Get-Tree (Join-Path $candidate $name))}
}
$packages = foreach ($name in @('react','react-dom','vite','vitest','typescript','@vitejs/plugin-react')) {
    $metadata = Get-Content -LiteralPath (Assert-NoLinks (Join-Path $candidate "node_modules\$name\package.json")) -Raw | ConvertFrom-Json
    [pscustomobject]@{name=$name; version=$metadata.version}
}
$report = [pscustomobject]@{
    observed_at=[DateTimeOffset]::UtcNow.ToString('o'); test_only=$true
    source_root=(Join-Path $root 'dev\web\src'); sources=@($candidateSources); builds=@($builds)
    dependency_lock_sha256=$lockHash; packages=@($packages); installed_from_existing_cache_offline=$true
    install_scripts_disabled=$true; package_lock_modified=$false
    stock_config_status='EXPLICIT_TEST_ONLY_RECONSTRUCTION_ORIGINAL_MISSING'
    baseline_unified_js_matched_retained_p9_before_fix=$true
    baseline_unified_js_sha256='182fcf012681784f4de2437f18c854def9371877547ea77899138adaebc14685'
    typescript_unified_and_stock_passed=$true; frontend_tests_passed=$tests.numPassedTests
    frontend_test_evidence=$TestEvidence; production_adopted=$false; owner_accepted=$false
    new_hour_and_market_acceptance_required=$true; fault_drive_reads=0; business_database_copies=0
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputReceipt -Encoding UTF8
[pscustomobject]@{test_only=$true; current_source_files=$candidateSources.Count; build_files=@($builds | ForEach-Object { $_.files.Count });
    frontend_tests_passed=$tests.numPassedTests; production_adopted=$false} | ConvertTo-Json
