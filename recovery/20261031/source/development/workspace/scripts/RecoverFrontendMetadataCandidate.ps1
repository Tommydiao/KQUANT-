$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\Desktop\Codex coding\kquant-safe-recovery-20261006'
$destination = Join-Path $root 'evidence\retained-frontend-metadata-20261007'
$archive = 'E:\KQUANT-Cloud-Recovery-20261006\one-minute-shadow.rar'
$memberRoot = 'outputs\one-minute-shadow\release-20260924T103058Z'
$manifestPath = 'E:\KQUANT-Cloud-Recovery-20261006\candidate-20260924T103058Z\outputs\one-minute-shadow\release-20260924T103058Z\manifest.json'
$unrar = 'C:\Program Files\WinRAR\UnRAR.exe'

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
$null = Assert-NoLinks $archive
$null = Assert-NoLinks $manifestPath
if ((Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
    '266fbf3e709c402b0af237ee92c6f974156444cd877ed7e5c94a0914db590439') {
    throw 'ORIGINAL_MANIFEST_CHANGED'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$names = @('package.json', 'package-lock.json', 'tsconfig.unified.json',
           'vite.unified.config.ts', 'unified.html', 'tokens.css')
foreach ($name in $names) {
    if (-not $manifest.files.PSObject.Properties['web/' + $name]) { throw 'MISSING_SOURCE_HASH' }
}
$null = New-Item -ItemType Directory -Path $destination
$files = foreach ($name in $names) {
    $member = "$memberRoot\source\web\$name"
    & $unrar e -idq -o- $archive $member ($destination + '\')
    if ($LASTEXITCODE -ne 0) { throw "EXTRACT_FAILED:$name" }
    $file = Assert-NoLinks (Join-Path $destination $name)
    $info = Get-Item -LiteralPath $file
    if ($info.PSIsContainer -or $info.Length -gt 2097152) { throw 'MEMBER_NOT_BOUNDED_FILE' }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = $manifest.files.PSObject.Properties['web/' + $name].Value
    if ($actual -ne $expected) { throw "MEMBER_HASH_MISMATCH:$name" }
    [pscustomobject]@{member=$member; path=$file; bytes=$info.Length; sha256=$actual; matches_original_20260924_manifest=$true}
}
$receipt = [pscustomobject]@{
    observed_at=[DateTimeOffset]::UtcNow.ToString('o'); archive=$archive
    source_release='release-20260924T103058Z'; source_manifest_sha256='266fbf3e709c402b0af237ee92c6f974156444cd877ed7e5c94a0914db590439'
    files=@($files); candidate_only=$true; matches_current_r58_dependencies='UNKNOWN'
    adopted_in_development=$false; adopted_in_production=$false; source_scripts_executed=$false
    production_writes=0; fault_drive_reads=0; business_databases_read=0
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $destination 'receipt.json') -Encoding UTF8
$receipt | ConvertTo-Json -Depth 6
