param([Parameter(Mandatory=$true)][string]$EvidencePath, [switch]$Leaf)
$ErrorActionPreference = 'Stop'
$child = $null
try {
  if (-not $Leaf) {
    $hostExe = (Get-Process -Id $PID).Path
    $arguments = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
      ('"' + $PSCommandPath + '"'), '-Leaf', '-EvidencePath', ('"' + $EvidencePath + '.leaf"'))
    $child = Start-Process -FilePath $hostExe -ArgumentList $arguments -WindowStyle Hidden -PassThru
  }
  $record = [ordered]@{ test_only=$true; pid=$PID; child_pid=$(if($child){$child.Id}); leaf=[bool]$Leaf }
  [IO.File]::WriteAllText($EvidencePath, ($record | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
  # A hard upper bound also cleans up if the acceptance driver is interrupted.
  Start-Sleep -Seconds 180
} finally {
  if ($child -and -not $child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }
}
