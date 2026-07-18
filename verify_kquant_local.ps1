param(
  [int]$Port = 8001,
  [switch]$SkipBuild,
  [switch]$SkipPytest,
  [switch]$SkipReadiness,
  [switch]$SkipSecretScan,
  [switch]$Strict
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
  param(
    [string]$Name,
    [string]$Status,
    [string]$Detail,
    [bool]$Critical = $true
  )
  $results.Add([pscustomobject]@{
    name = $Name
    status = $Status
    critical = $Critical
    detail = $Detail
  })
}

function Test-PythonExecutable {
  param([string]$Executable)
  if (-not $Executable) {
    return $false
  }
  try {
    $version = & $Executable --version 2>&1
    return ($LASTEXITCODE -eq 0 -and (($version -join " ") -match "Python"))
  } catch {
    return $false
  }
}

function Resolve-KquantPython {
  $venvPython = Join-Path $Root ".venv-win\Scripts\python.exe"
  if ((Test-Path $venvPython) -and (Test-PythonExecutable $venvPython)) {
    return $venvPython
  }

  if (Test-PythonExecutable "python") {
    return "python"
  }

  try {
    $pyList = & py -0p 2>$null
    if ($LASTEXITCODE -eq 0) {
      $candidate = @($pyList | Where-Object { $_ -match "python\.exe" } | Select-Object -First 1)
      if ($candidate -and (Test-PythonExecutable $candidate)) {
        return $candidate
      }
    }
  } catch {
    # Leave unresolved. The caller will print setup guidance.
  }

  return $null
}

function Show-PythonSetupGuidance {
  Write-Host ""
  Write-Host "Python test runtime is not available." -ForegroundColor Yellow
  Write-Host "Fix it on this PC with:" -ForegroundColor Yellow
  Write-Host "  Remove-Item -Recurse -Force .\.venv-win" -ForegroundColor DarkGray
  Write-Host "  python -m venv .venv-win" -ForegroundColor DarkGray
  Write-Host "  .\.venv-win\Scripts\python -m pip install --upgrade pip" -ForegroundColor DarkGray
  Write-Host "  .\.venv-win\Scripts\python -m pip install -e `".[dev]`"" -ForegroundColor DarkGray
}

function Invoke-NpmBuildWithRetry {
  $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npm) {
    $npm = (Get-Command npm -ErrorAction Stop).Source
  }

  & $npm run build
  $exitCode = $LASTEXITCODE
  if ($exitCode -eq 0) {
    $script:LastNpmBuildExitCode = 0
    return
  }

  $viteTempPath = Join-Path (Get-Location) "node_modules\.vite-temp"
  $webRoot = (Resolve-Path ".").Path
  $resolvedTemp = Resolve-Path $viteTempPath -ErrorAction SilentlyContinue
  if ($resolvedTemp -and $resolvedTemp.Path.StartsWith($webRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "Build failed. Clearing Vite temp cache and retrying once: $($resolvedTemp.Path)" -ForegroundColor Yellow
    Remove-Item -LiteralPath $resolvedTemp.Path -Recurse -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    & $npm run build
    $script:LastNpmBuildExitCode = $LASTEXITCODE
    return
  }

  $script:LastNpmBuildExitCode = $exitCode
}

function Find-PlaintextSecrets {
  # Prefer Git's view of tracked and non-ignored project files. Virtual
  # environments contain SDK examples that can resemble real token formats and
  # must never be treated as repository-owned source.
  $relativePaths = @(& git -C $Root ls-files --cached --others --exclude-standard 2>$null)
  if ($LASTEXITCODE -eq 0 -and $relativePaths.Count -gt 0) {
    $files = @($relativePaths |
      Where-Object { $_ -notmatch '(^|/)\.env' } |
      ForEach-Object { Join-Path $Root $_ } |
      Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
  } else {
    $excluded = @(".git", "node_modules", "dist", "work", "outputs", ".pytest_cache")
    $files = Get-ChildItem -Path $Root -File -Recurse | Where-Object {
      $pathParts = $_.FullName.Substring($Root.Length).TrimStart("\\") -split "\\"
      -not ($pathParts | Where-Object { $excluded -contains $_ -or $_ -like ".venv*" }) -and
      $_.Name -notmatch "^\.env"
    } | Select-Object -ExpandProperty FullName
  }
  $pattern = '(?i)(sk-(?:proj|live|test)-[A-Za-z0-9_-]{20,}|ap_[A-Za-z0-9._~-]{20,})'
  return @($files | ForEach-Object {
    Select-String -LiteralPath $_ -Pattern $pattern -ErrorAction SilentlyContinue
  })
}

Write-Host "KQUANT local verification" -ForegroundColor Cyan
Write-Host "Root: $Root" -ForegroundColor DarkGray
Write-Host "Backend target: http://127.0.0.1:$Port/" -ForegroundColor DarkGray
Write-Host ""

if ($SkipBuild) {
  Add-Result "frontend_build" "skipped" "Skipped by -SkipBuild." $false
} else {
  try {
    Push-Location (Join-Path $Root "web")
    $script:LastNpmBuildExitCode = 1
    Invoke-NpmBuildWithRetry
    $buildExitCode = $script:LastNpmBuildExitCode
    if ($buildExitCode -eq 0) {
      Add-Result "frontend_build" "passed" "npm run build passed."
    } else {
      Add-Result "frontend_build" "failed" "npm run build exited with code $buildExitCode."
    }
  } catch {
    Add-Result "frontend_build" "failed" $_.Exception.Message
  } finally {
    Pop-Location
  }
}

if ($SkipSecretScan) {
  Add-Result "plaintext_secret_scan" "skipped" "Skipped by -SkipSecretScan." $false
} else {
  try {
    $secretMatches = Find-PlaintextSecrets
    if ($secretMatches.Count -eq 0) {
      Add-Result "plaintext_secret_scan" "passed" "No plaintext credential assignment patterns found."
    } else {
      $locations = @($secretMatches | Select-Object -First 5 | ForEach-Object { "$($_.Path):$($_.LineNumber)" }) -join ", "
      Add-Result "plaintext_secret_scan" "failed" "Potential plaintext credential pattern(s) found at $locations. Values are intentionally not printed."
    }
  } catch {
    Add-Result "plaintext_secret_scan" "failed" $_.Exception.Message
  }
}

if ($SkipReadiness) {
  Add-Result "monday_readiness" "skipped" "Skipped by -SkipReadiness." $false
} else {
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "check_kquant_monday_pilot.ps1") -Port $Port
    if ($LASTEXITCODE -eq 0) {
      Add-Result "monday_readiness" "passed" "Critical live/AI/safety checks passed."
    } elseif ($LASTEXITCODE -eq 2) {
      Add-Result "monday_readiness" "warning" "Critical checks passed with warnings." $false
    } else {
      Add-Result "monday_readiness" "failed" "Readiness check exited with code $LASTEXITCODE."
    }
  } catch {
    Add-Result "monday_readiness" "failed" $_.Exception.Message
  }
}

if ($SkipPytest) {
  Add-Result "python_pytest" "skipped" "Skipped by -SkipPytest." $false
} else {
  $python = Resolve-KquantPython
  if (-not $python) {
    Add-Result "python_pytest" "skipped" "No usable Python runtime found for pytest." ([bool]$Strict)
    Show-PythonSetupGuidance
  } else {
    try {
      & $python -m pytest -q
      if ($LASTEXITCODE -eq 0) {
        Add-Result "python_pytest" "passed" "pytest passed with $python."
      } else {
        Add-Result "python_pytest" "failed" "pytest exited with code $LASTEXITCODE using $python."
      }
    } catch {
      Add-Result "python_pytest" "failed" $_.Exception.Message
    }
  }
}

Write-Host ""
$results | Format-Table -AutoSize

$failedCritical = @($results | Where-Object { $_.critical -and $_.status -eq "failed" })
$skippedCritical = @($results | Where-Object { $_.critical -and $_.status -eq "skipped" })
$warnings = @($results | Where-Object { $_.status -eq "warning" -or ((-not $_.critical) -and $_.status -in @("failed", "skipped")) })

Write-Host ""
if ($failedCritical.Count -gt 0 -or $skippedCritical.Count -gt 0) {
  Write-Host "NOT READY: $($failedCritical.Count + $skippedCritical.Count) critical verification item(s) failed or were skipped." -ForegroundColor Red
  exit 1
}

if ($warnings.Count -gt 0) {
  Write-Host "READY WITH CAUTION: critical checks passed, but $($warnings.Count) warning item(s) need attention." -ForegroundColor Yellow
  exit 2
}

Write-Host "READY: build, credential scan, readiness, and pytest checks passed." -ForegroundColor Green
exit 0
