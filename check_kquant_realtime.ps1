param(
  [int]$Port = 8001,
  [string]$Symbol = "NVDA"
)

$ErrorActionPreference = "Stop"
$BaseUrl = "http://127.0.0.1:$Port"
$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Invoke-KquantJson {
  param([string]$Path)
  $response = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl$Path" -TimeoutSec 30
  if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
    throw "HTTP $($response.StatusCode): $Path"
  }
  return $response.Content | ConvertFrom-Json
}

Write-Host "KQUANT realtime market data check" -ForegroundColor Cyan
Write-Host "Backend: $BaseUrl" -ForegroundColor DarkGray
Write-Host "Symbol: $Symbol" -ForegroundColor DarkGray
Write-Host ""

try {
  $health = Invoke-KquantJson "/api/health"
  if ($health.status -ne "online") {
    $failures.Add("Backend status is $($health.status).")
  }
} catch {
  $failures.Add("Backend is offline: $($_.Exception.Message)")
}

if ($failures.Count -eq 0) {
  try {
    $status = Invoke-KquantJson "/api/stocks/market-data/status"
    if ($status.provider -ne "longbridge") {
      $failures.Add("Active provider is $($status.provider), not longbridge.")
    }
    if ($status.longbridge_env -ne "configured") {
      $failures.Add("Longbridge credentials are not configured.")
    }
    if ($status.longbridge_sdk -ne "installed") {
      $failures.Add("Longbridge SDK is not installed.")
    }
    if ($status.longbridge_account_enabled -or $status.longbridge_trade_enabled) {
      $failures.Add("Longbridge account/trade context must remain disabled.")
    }
    Write-Host "Provider: $($status.provider)" -ForegroundColor Green
    Write-Host "SDK: $($status.longbridge_sdk); credentials: $($status.longbridge_env)" -ForegroundColor DarkGray
  } catch {
    $failures.Add("Market-data status failed: $($_.Exception.Message)")
  }

  try {
    $check = Invoke-KquantJson "/api/stocks/market-data/self-check?symbol=$Symbol"
    $quoteCheck = @($check.checks | Where-Object { $_.name -eq "quote_entitlement" } | Select-Object -First 1)
    if (-not $quoteCheck -or $quoteCheck[0].status -ne "pass") {
      $failures.Add("Longbridge quote entitlement did not pass.")
    }
    if (-not $check.no_account_or_order_path) {
      $failures.Add("Safety check detected an account or order path.")
    }
    if ($check.market_clock.session -ne "regular") {
      $warnings.Add("US market session is $($check.market_clock.session); realtime buy triggers are correctly disabled outside regular hours.")
    } elseif (-not $check.realtime_buy_data_ready) {
      $failures.Add("US market is regular, but realtime quote freshness is not trade-ready.")
    }
    Write-Host "Self-check: $($check.status); session=$($check.market_clock.session)" -ForegroundColor Green
  } catch {
    $failures.Add("Longbridge self-check failed: $($_.Exception.Message)")
  }

  try {
    $snapshot = Invoke-KquantJson "/api/stocks/realtime-snapshot?symbol=$Symbol"
    if ($snapshot.provider -ne "longbridge" -and $snapshot.quote.provider -ne "longbridge") {
      $failures.Add("Realtime snapshot is not sourced from Longbridge.")
    }
    if ($snapshot.data_trust.state -notin @("live_trade_eligible", "reference_only")) {
      $failures.Add("Realtime snapshot trust state is $($snapshot.data_trust.state).")
    }
    Write-Host "Quote: $($snapshot.quote.last) at $($snapshot.quote.quote_time)" -ForegroundColor Green
    Write-Host "Trust: $($snapshot.data_trust.state); quote age=$($snapshot.quote.freshness_seconds)s" -ForegroundColor DarkGray
  } catch {
    $failures.Add("Realtime snapshot failed: $($_.Exception.Message)")
  }
}

Write-Host ""
if ($failures.Count -gt 0) {
  Write-Host "REALTIME CHECK FAILED" -ForegroundColor Red
  foreach ($failure in $failures) {
    Write-Host "  - $failure" -ForegroundColor Red
  }
  exit 1
}

if ($warnings.Count -gt 0) {
  Write-Host "REALTIME CHECK READY FOR REFERENCE" -ForegroundColor Yellow
  foreach ($warning in $warnings) {
    Write-Host "  - $warning" -ForegroundColor Yellow
  }
  exit 2
}

Write-Host "REALTIME CHECK PASSED" -ForegroundColor Green
Write-Host "Longbridge quote data is fresh for the US regular session." -ForegroundColor Green
exit 0
