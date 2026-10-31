$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\Desktop\Codex coding\kquant-safe-recovery-20261006'
$metadata = Join-Path $root 'evidence\retained-frontend-metadata-20261007'
$source = Join-Path $root 'dev\web\src'
$destination = Join-Path $root 'evidence\frontend-build-candidate-20261007'

function Assert-NoLinks([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    if ($full -match '^[Ff]:') { throw 'FAULT_DRIVE_FORBIDDEN' }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_PATH_FORBIDDEN' }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
    return $full
}

$destination = Assert-NoLinks $destination
if (-not $destination.StartsWith($root + '\evidence\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ISOLATION_BOUNDARY'
}
if (Test-Path -LiteralPath $destination) { throw 'FRESH_CANDIDATE_REQUIRED' }
$source = Assert-NoLinks $source
$receiptPath = Assert-NoLinks (Join-Path $metadata 'receipt.json')
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if (-not $receipt.candidate_only -or $receipt.adopted_in_production) { throw 'UNEXPECTED_METADATA_STATUS' }
$inputs = [Collections.Generic.List[object]]::new()
foreach ($row in $receipt.files) {
    $path = Assert-NoLinks $row.path
    if (-not $path.StartsWith($metadata + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'METADATA_BOUNDARY' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256) {
        throw 'METADATA_CHANGED'
    }
    $inputs.Add([pscustomobject]@{source=$path; relative=[IO.Path]::GetFileName($path); sha256=$row.sha256})
}

$pending = [Collections.Generic.Queue[string]]::new()
$pending.Enqueue($source)
while ($pending.Count) {
    $directory = Assert-NoLinks $pending.Dequeue()
    foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
        $path = Assert-NoLinks $item.FullName
        if ($item.PSIsContainer) { $pending.Enqueue($path); continue }
        if ($item.Length -gt 2097152 -or $inputs.Count -ge 256) { throw 'SOURCE_BUDGET_EXCEEDED' }
        $relative = 'src\' + $path.Substring($source.Length + 1)
        $inputs.Add([pscustomobject]@{
            source=$path; relative=$relative
            sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    }
}
$null = New-Item -ItemType Directory -Path $destination
foreach ($row in $inputs) {
    $target = Assert-NoLinks (Join-Path $destination $row.relative)
    if (-not $target.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'TARGET_BOUNDARY' }
    $parent = [IO.Path]::GetDirectoryName($target)
    $null = New-Item -ItemType Directory -Path $parent -Force
    Copy-Item -LiteralPath $row.source -Destination $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256 -or
        (Get-FileHash -LiteralPath $row.source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256) {
        throw 'COPY_OR_SOURCE_CHANGED'
    }
}
$report = [pscustomobject]@{
    observed_at=[DateTimeOffset]::UtcNow.ToString('o'); test_only=$true; destination=$destination
    metadata_release=$receipt.source_release; current_source_root=$source; files=@($inputs.ToArray())
    metadata_matches_current_release='UNKNOWN'; adopted_in_production=$false
    builds_run=$false; dependencies_installed=$false; fault_drive_reads=0; business_database_copies=0
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $destination 'preparation_receipt.json') -Encoding UTF8
[pscustomobject]@{destination=$destination; test_only=$true; copied_files=$inputs.Count; adopted_in_production=$false} | ConvertTo-Json
