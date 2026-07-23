param(
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Resolve-KquantPython {
  $candidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root ".venv-win\Scripts\python.exe")
  )
  foreach ($candidate in $candidates) {
    if ((Test-Path $candidate) -and ((& $candidate --version 2>&1) -match "Python")) {
      return $candidate
    }
  }
  throw "No working KQUANT virtual environment was found. Create .venv and install .[dev]."
}

$Python = Resolve-KquantPython
Write-Host "KQUANT verification using $Python" -ForegroundColor Cyan

& $Python -m compileall -q kquant scripts tests
& $Python -m pytest -q
& $Python scripts/verify_read_only_boundary.py

if (-not $SkipFrontend) {
  Push-Location web
  try {
    & npm.cmd run lint
    & npm.cmd test
    & npm.cmd run build
  } finally {
    Pop-Location
  }
}

Write-Host "KQUANT verification passed." -ForegroundColor Green
