$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\Desktop\Codex coding\kquant-safe-recovery-20261006'
$destination = Join-Path $root 'evidence\frontend-build-candidate-20261007'

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

$destination = Assert-NoLinks $destination
$receipt = Get-Content -LiteralPath (Assert-NoLinks (Join-Path $root 'evidence\retained-frontends-20261007\receipt.json')) -Raw | ConvertFrom-Json
$rows = foreach ($entry in @(
    @{build='candidate-dist-unified'; folder='unified-public'; names=@('kq-mark.svg','manifest.webmanifest','service-worker.js')},
    @{build='candidate-dist-stock'; folder='stock-public'; names=@('kquant-mark.svg','manifest.webmanifest','service-worker.js')}
)) {
    $build = $receipt.builds.PSObject.Properties[$entry.build].Value
    $folder = Assert-NoLinks (Join-Path $destination $entry.folder)
    if (-not $folder.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase) -or
        (Test-Path -LiteralPath $folder)) { throw 'FRESH_PUBLIC_DIRECTORY_REQUIRED' }
    $null = New-Item -ItemType Directory -Path $folder
    foreach ($name in $entry.names) {
        $source = Assert-NoLinks (Join-Path $build.path $name)
        $expected = $build.files.PSObject.Properties[$name].Value.sha256
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw 'RETAINED_PUBLIC_HASH_CHANGED'
        }
        $target = Assert-NoLinks (Join-Path $folder $name)
        Copy-Item -LiteralPath $source -Destination $target
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw 'PUBLIC_COPY_HASH_CHANGED'
        }
        [pscustomobject]@{source=$source; target=$target; sha256=$expected; matches_retained_p9=$true}
    }
}
[pscustomobject]@{observed_at=[DateTimeOffset]::UtcNow.ToString('o'); test_only=$true;
    files=@($rows); production_adopted=$false; fault_drive_reads=0; database_copies=0} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $destination 'public_receipt.json') -Encoding UTF8
"TEST_ONLY: $($rows.Count) static files verified and copied."
