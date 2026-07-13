param(
  [int]$Port = 8001,
  [string[]]$Symbols = @("NVDA", "RKLB", "MSTR"),
  [string]$Profile = "high_beta_growth_v1",
  [string]$OutputsDir = "outputs"
)

$ErrorActionPreference = "Continue"
$DashboardUrl = "http://127.0.0.1:$Port"
$Checks = New-Object System.Collections.Generic.List[object]
$GeneratedAt = (Get-Date).ToUniversalTime().ToString("o")
$RunId = "monday-readiness-" + (Get-Date -Format "yyyyMMdd-HHmmss")

function Add-Check {
  param(
    [string]$Name,
    [bool]$Passed,
    [string]$Detail,
    [bool]$Critical = $false
  )
  $Checks.Add([pscustomobject]@{
    name = $Name
    passed = $Passed
    critical = $Critical
    detail = $Detail
  })
}

function Invoke-KquantJson {
  param([string]$Path)
  $response = Invoke-WebRequest -UseBasicParsing "$DashboardUrl$Path" -TimeoutSec 20
  if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
    throw "HTTP $($response.StatusCode) for $Path"
  }
  return $response.Content | ConvertFrom-Json
}

function Convert-ReadinessMarkdown {
  param(
    [string]$Status,
    [object[]]$CriticalFailed,
    [object[]]$Warnings
  )

  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# KQUANT Monday Pilot Readiness")
  $lines.Add("")
  $lines.Add("- Run ID: ``$RunId``")
  $lines.Add("- Generated UTC: ``$GeneratedAt``")
  $lines.Add("- Dashboard: ``$DashboardUrl``")
  $lines.Add("- Profile: ``$Profile``")
  $lines.Add("- Symbols: ``$($Symbols -join ', ')``")
  $lines.Add("- Status: **$Status**")
  $lines.Add("")
  $lines.Add("## Summary")
  $lines.Add("")
  $lines.Add("- Critical failures: ``$($CriticalFailed.Count)``")
  $lines.Add("- Warnings: ``$($Warnings.Count)``")
  $lines.Add("- Safety mode: ``read-only research; no broker/order path``")
  $lines.Add("")
  $lines.Add("## Checks")
  $lines.Add("")
  $lines.Add("| Check | Critical | Passed | Detail |")
  $lines.Add("| --- | --- | --- | --- |")
  foreach ($check in $Checks) {
    $detail = (($check.detail -replace "\|", "/") -replace "`r?`n", " ")
    $lines.Add("| $($check.name) | $($check.critical) | $($check.passed) | $detail |")
  }
  $lines.Add("")
  $lines.Add("## Pilot Rules")
  $lines.Add("")
  $lines.Add("- Stocks only; no options, no leveraged ETFs, no automatic execution.")
  $lines.Add("- Max account risk per trade: ``0.25%``.")
  $lines.Add("- First day max trades: ``1-2``.")
  $lines.Add("- Total first-day risk: ``0.5%``.")
  $lines.Add("- Journal before entry; no trade during provider/data caution.")
  return ($lines -join [Environment]::NewLine)
}

function Write-ReadinessArtifacts {
  param(
    [string]$Status,
    [object[]]$CriticalFailed,
    [object[]]$Warnings
  )

  $outputPath = Join-Path (Get-Location) $OutputsDir
  New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

  $jsonPath = Join-Path $outputPath "monday-pilot-readiness.json"
  $mdPath = Join-Path $outputPath "monday-pilot-readiness.md"

  $checkRows = @($Checks | ForEach-Object {
    [ordered]@{
      name = $_.name
      passed = [bool]$_.passed
      critical = [bool]$_.critical
      detail = [string]$_.detail
    }
  })
  $criticalRows = @($CriticalFailed | ForEach-Object {
    [ordered]@{
      name = $_.name
      passed = [bool]$_.passed
      critical = [bool]$_.critical
      detail = [string]$_.detail
    }
  })
  $warningRows = @($Warnings | ForEach-Object {
    [ordered]@{
      name = $_.name
      passed = [bool]$_.passed
      critical = [bool]$_.critical
      detail = [string]$_.detail
    }
  })

  $payload = [ordered]@{
    run_id = $RunId
    generated_at_utc = $GeneratedAt
    dashboard_url = $DashboardUrl
    profile = $Profile
    symbols = @($Symbols)
    status = $Status
    critical_failure_count = $CriticalFailed.Count
    warning_count = $Warnings.Count
    critical_failures = $criticalRows
    warnings = $warningRows
    checks = $checkRows
    safety = [ordered]@{
      read_only_research = $true
      broker_order_wiring_enabled = $false
      account_access_enabled = $false
      order_submission_enabled = $false
    }
    pilot_rules = [ordered]@{
      stocks_only = $true
      max_account_risk_per_trade_pct = 0.25
      first_day_max_trades = "1-2"
      total_first_day_risk_pct = 0.5
      journal_before_entry = $true
      no_trade_during_data_caution = $true
    }
  }

  $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath -Encoding UTF8
  Convert-ReadinessMarkdown -Status $Status -CriticalFailed $CriticalFailed -Warnings $Warnings | Set-Content -Path $mdPath -Encoding UTF8
  Write-Host "Readiness artifacts written:" -ForegroundColor DarkGray
  Write-Host "  $jsonPath" -ForegroundColor DarkGray
  Write-Host "  $mdPath" -ForegroundColor DarkGray
}

Write-Host "KQUANT Monday manual pilot preflight" -ForegroundColor Cyan
Write-Host "Target: $DashboardUrl" -ForegroundColor DarkGray
Write-Host "Mode: read-only research; no broker/order path is allowed." -ForegroundColor DarkGray
Write-Host ""

try {
  $health = Invoke-KquantJson "/api/health"
  Add-Check "backend_online" ($health.status -eq "online") "status=$($health.status)" $true
  Add-Check "live_data_enabled" ([bool]$health.live_data_enabled) "live_data_enabled=$($health.live_data_enabled)" $true
  Add-Check "fixture_hidden" (-not [bool]$health.fixture_user_visible) "fixture_user_visible=$($health.fixture_user_visible)" $true
  Add-Check "broker_disabled" (-not [bool]$health.broker_order_wiring_enabled) "broker_order_wiring_enabled=$($health.broker_order_wiring_enabled)" $true
  Add-Check "account_disabled" (-not [bool]$health.account_access_enabled) "account_access_enabled=$($health.account_access_enabled)" $true
  Add-Check "orders_disabled" (-not [bool]$health.order_submission_enabled) "order_submission_enabled=$($health.order_submission_enabled)" $true
} catch {
  Add-Check "backend_online" $false $_.Exception.Message $true
}

try {
  $marketData = Invoke-KquantJson "/api/stocks/market-data/self-check?symbol=$($Symbols[0])"
  $quoteCheck = @($marketData.checks | Where-Object { $_.name -eq "quote_entitlement" } | Select-Object -First 1)[0]
  Add-Check "longbridge_market_data" ($marketData.status -in @("ready", "caution")) "status=$($marketData.status); provider=$($marketData.quote.provider); quote_status=$($marketData.quote.provider_status)" $true
  Add-Check "longbridge_quote_entitlement" ($quoteCheck.status -eq "pass") "status=$($quoteCheck.status); quote_time=$($quoteCheck.quote_time)" $true
  Add-Check "no_longbridge_trade_context" ([bool]$marketData.no_account_or_order_path) "no_account_or_order_path=$($marketData.no_account_or_order_path)" $true
  if ($marketData.market_clock.session -ne "regular") {
    Add-Check "regular_session_live_trigger" $false "US regular session is $($marketData.market_clock.session); realtime entry triggers are disabled outside the regular session." $false
  } elseif (-not [bool]$marketData.realtime_buy_data_ready) {
    Add-Check "regular_session_live_trigger" $false "Quote is not fresh enough for a real-money entry trigger." $true
  } else {
    Add-Check "regular_session_live_trigger" $true "Longbridge quote is fresh during the US regular session." $true
  }
} catch {
  Add-Check "longbridge_market_data" $false $_.Exception.Message $true
}

try {
  $ai = Invoke-KquantJson "/api/stocks/ai-review/status"
  Add-Check "ai_available" ($ai.status -eq "available") "status=$($ai.status); model=$($ai.models.review)" $true
  Add-Check "ai_cannot_order" (-not [bool]$ai.ai_can_place_orders -and -not [bool]$ai.order_submission_enabled) "ai_can_place_orders=$($ai.ai_can_place_orders)" $true
  Add-Check "hard_veto_enabled" ([bool]$ai.hard_rule_veto_enabled) "hard_rule_veto_enabled=$($ai.hard_rule_veto_enabled)" $true
} catch {
  Add-Check "ai_available" $false $_.Exception.Message $true
}

try {
  $daily = Invoke-KquantJson "/api/stocks/ai-daily-report/latest"
  Add-Check "ai_daily_available" ($daily.status -eq "available") "status=$($daily.status); run_id=$($daily.run_id)" $true
  Add-Check "ai_daily_fresh" (-not [bool]$daily.is_stale) "market_date=$($daily.market_date); age_seconds=$($daily.age_seconds)" $true
  $topCount = @($daily.ai_report.top_buy_candidates).Count
  Add-Check "ai_buy_candidates_optional" ($topCount -ge 0) "top_buy_candidates=$topCount" $false
} catch {
  Add-Check "ai_daily_available" $false $_.Exception.Message $true
}

foreach ($symbol in $Symbols) {
  try {
    $dailyCandles = Invoke-KquantJson "/api/stocks/candles?symbol=$symbol&range=1y&interval=1d&source=live"
    Add-Check "$symbol daily_live_candles" (($dailyCandles.provider_status -eq "available") -and (@($dailyCandles.candles).Count -gt 0) -and ($dailyCandles.source_type -notmatch "fixture")) "status=$($dailyCandles.provider_status); source=$($dailyCandles.source_type); candles=$(@($dailyCandles.candles).Count)" $true
  } catch {
    Add-Check "$symbol daily_live_candles" $false $_.Exception.Message $true
  }

  try {
    $confirmCandles = Invoke-KquantJson "/api/stocks/candles?symbol=$symbol&range=5d&interval=1h&source=live"
    Add-Check "$symbol confirm_live_candles" (($confirmCandles.provider_status -eq "available") -and (@($confirmCandles.candles).Count -gt 0) -and ($confirmCandles.source_type -notmatch "fixture")) "status=$($confirmCandles.provider_status); source=$($confirmCandles.source_type); candles=$(@($confirmCandles.candles).Count)" $true
  } catch {
    Add-Check "$symbol confirm_live_candles" $false $_.Exception.Message $true
  }

  try {
    $analysis = Invoke-KquantJson "/api/stocks/analyze?symbol=$symbol&source=live&profile=$Profile"
    $signal = $analysis.signal
    $hardBlocked = ($signal.readiness_gate.status -eq "BLOCKED")
    Add-Check "$symbol analyze_payload" ($null -ne $signal) "level=$($signal.level); action=$($signal.trade_conclusion.action); readiness=$($signal.readiness_gate.status)" $true
    if ($signal.trade_conclusion.action -eq "BUY" -and $hardBlocked) {
      Add-Check "$symbol buy_guardrail" $false "BUY appeared while readiness gate is BLOCKED." $true
    } else {
      Add-Check "$symbol buy_guardrail" $true "No BUY bypass of readiness gate detected." $true
    }
  } catch {
    Add-Check "$symbol analyze_payload" $false $_.Exception.Message $true
  }
}

$Checks | Format-Table -AutoSize

$criticalFailed = @($Checks | Where-Object { $_.critical -and -not $_.passed })
$warnings = @($Checks | Where-Object { -not $_.critical -and -not $_.passed })

Write-Host ""
if ($criticalFailed.Count -gt 0) {
  Write-ReadinessArtifacts "NO_TRADE" $criticalFailed $warnings
  Write-Host "NO TRADE: $($criticalFailed.Count) critical check(s) failed." -ForegroundColor Red
  exit 1
}

if ($warnings.Count -gt 0) {
  Write-ReadinessArtifacts "CAUTION" $criticalFailed $warnings
  Write-Host "CAUTION: critical checks passed, but $($warnings.Count) warning check(s) failed." -ForegroundColor Yellow
  exit 2
}

Write-ReadinessArtifacts "READY" $criticalFailed $warnings
Write-Host "READY: critical checks passed. Manual pilot rules still apply: max 0.25% account risk per trade, max 1-2 trades, journal before entry." -ForegroundColor Green
exit 0
