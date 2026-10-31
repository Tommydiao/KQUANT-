param([Parameter(Mandatory=$true)][string]$Projection)
$ErrorActionPreference = 'Stop'
$p = Get-Content -LiteralPath $Projection -Raw | ConvertFrom-Json
$release = Get-Content -LiteralPath $p.release_manifest.path -Raw | ConvertFrom-Json
$entry = Get-Content -LiteralPath $p.proposed_entry.path -Raw | ConvertFrom-Json
$pending = @{}
foreach ($row in $p.changes) { $pending[$row.target] = $row.payload }
$declared = @{}
$count = 0
foreach ($section in @('files','retained_source_hashes','frontend_files','configuration_hashes','source_fact_hashes')) {
  foreach ($item in $release.$section.PSObject.Properties) {
    $expected = if ($section -eq 'files') { $item.Value.sha256 } else { $item.Value }
    if ($declared.ContainsKey($item.Name) -and $declared[$item.Name] -ne $expected) {
      throw ('RELEASE_SECTION_HASH_CONFLICT:' + $item.Name)
    }
    $declared[$item.Name] = $expected
    $path = if ($pending.ContainsKey($item.Name)) { $pending[$item.Name] } else { Join-Path $entry.code_root $item.Name }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
      throw ('PROJECTED_ORIGINAL_HOST_HASH_FAILURE:' + $item.Name)
    }
    $count++
  }
}
[pscustomobject]@{
  observed_at = [DateTime]::UtcNow.ToString('o')
  host_executable = (Get-Process -Id $PID).Path
  version = $PSVersionTable.PSVersion.ToString()
  candidate_id = $p.candidate_id
  declaration_checks = $count
  all_passed = $true
  production_writes = 0
  sdk_connections = 0
} | ConvertTo-Json -Compress
