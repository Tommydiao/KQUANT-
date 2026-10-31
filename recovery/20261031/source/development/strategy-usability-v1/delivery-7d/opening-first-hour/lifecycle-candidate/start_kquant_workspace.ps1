param(
  [switch]$KillExisting,
  [switch]$GatewayOnly,
  [switch]$OptionsFoundation,
  [switch]$TwoHourResearch,
  [switch]$OneMinuteShadow,
  [string]$UnifiedWebDist = "",
  [string]$RuntimeManifest = "",
  [string]$CapabilityEvidence = "",
  [string]$RecoveryManifest = "",
  [string]$RuntimeRoot = "",
  [string]$PythonExecutable = "",
  [string[]]$RecoveryLocalRoot = @(),
  [string]$LanAddress = "",
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CryptoRoot = Join-Path $Root "crypto"
function Assert-SafeRecoveryLocalPath {
  param([string]$Path)
  $absolute = [IO.Path]::GetFullPath($Path)
  if (-not [IO.Path]::IsPathRooted($Path) -or $absolute -notmatch '^[CDE]:\\' -or $absolute.Substring(2).Contains(':')) { throw "SAFE_RECOVERY_PATH_NOT_ON_APPROVED_LOCAL_DRIVE" }
  $parents = [Collections.Generic.List[string]]::new()
  for ($item = $absolute; $item; $item = [IO.Path]::GetDirectoryName($item)) { $parents.Add($item) }
  for ($index = $parents.Count - 1; $index -ge 0; $index--) {
    $entry = Get-Item -LiteralPath $parents[$index] -Force -ErrorAction SilentlyContinue
    if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "SAFE_RECOVERY_REPARSE_PATH" }
  }
}
Assert-SafeRecoveryLocalPath $Root
$DataRoot = $Root
if ($RuntimeRoot) {
  Assert-SafeRecoveryLocalPath $RuntimeRoot
  $DataRoot = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
  if (-not $PythonExecutable) { throw "EXPLICIT_RUNTIME_REQUIRES_PINNED_PYTHON" }
}
if ($PythonExecutable) {
  Assert-SafeRecoveryLocalPath $PythonExecutable
  $PythonExecutable = [IO.Path]::GetFullPath($PythonExecutable)
}
. (Join-Path $Root 'scripts/FoundationLifecycle.ps1')
$script:RunSessionId = [guid]::NewGuid().ToString()
$script:LaunchStamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$script:FoundationStage = 'PREFLIGHT'
$script:RequestedReleaseId = if ($RuntimeManifest) { Split-Path -Leaf (Split-Path -Parent $RuntimeManifest) } else { 'UNDECLARED' }
$env:KQUANT_LAUNCHER_HOST = (Get-Process -Id $PID).Path
$script:StartedServices = @()
$script:OwnedListenerIdentities = @()
$script:FoundationOwnsMutex = $false
$recoveryCount = 0
$launcherExitReason = 'LAUNCHER_EXITED_WITHOUT_CONFIRMED_SERVICE_STOP'
$env:KQUANT_BACKEND_RELEASE_ID = 'UNVERIFIED_WORKING_TREE'
$env:KQUANT_BACKEND_MANIFEST_SHA256 = ''
try {
if ($OptionsFoundation) {
  $foundationRoot = Join-Path $DataRoot 'work\option_foundation\runtime'
  New-Item -ItemType Directory -Force -Path $foundationRoot | Out-Null
  $serviceManifest = Join-Path $foundationRoot 'services.json'
  $script:LauncherIdentity = Get-FoundationProcessIdentity $PID
  $script:SystemBoot = Get-FoundationSystemBoot
  Write-FoundationLifecycle 'PREFLIGHT' 'EXPLICIT_START'
}
$env:KQUANT_RUNTIME_PATH_BINDING = ""
$env:KQUANT_RUNTIME_PATH_BINDING_SHA256 = ""
$env:KQUANT_RUNTIME_DATA_ROOT = ""
# Recovery is checked before credentials or business modules; lifecycle only writes small diagnostics.
$recoveryGate = Join-Path $Root "config\safe_recovery_required.json"
Assert-SafeRecoveryLocalPath $recoveryGate
if (($RuntimeRoot -or $PythonExecutable) -and -not (Test-Path -LiteralPath $recoveryGate)) {
  throw "EXPLICIT_RUNTIME_REQUIRES_RECOVERY_GATE"
}
if (Test-Path -LiteralPath $recoveryGate) {
  if (-not $RecoveryManifest) { throw "SAFE_RECOVERY_REQUIRED: supply an exact verified recovery manifest; no services started." }
  $manifestAbsolute = [IO.Path]::GetFullPath($RecoveryManifest)
  Assert-SafeRecoveryLocalPath $manifestAbsolute
  $recoveryPython = if ($PythonExecutable) { $PythonExecutable } else { Join-Path $Root ".venv\Scripts\python.exe" }
  Assert-SafeRecoveryLocalPath $recoveryPython
  if (-not (Test-Path -LiteralPath $recoveryPython)) { throw "SAFE_RECOVERY_DEPENDENCIES_MISSING: no fallback to an old Python environment." }
  $venvConfig = Join-Path (Split-Path -Parent (Split-Path -Parent $recoveryPython)) "pyvenv.cfg"
  Assert-SafeRecoveryLocalPath $venvConfig
  if (-not (Test-Path -LiteralPath $venvConfig)) { throw "SAFE_RECOVERY_PYTHON_CONFIG_MISSING" }
  if ((Get-Content -LiteralPath $venvConfig -Raw) -match '(?i)F:[\\/]') { throw "SAFE_RECOVERY_PYTHON_STILL_REFERENCES_FAULT_DRIVE" }
  $recoveryChecker = Join-Path $Root "scripts\check_safe_recovery.py"
  Assert-SafeRecoveryLocalPath $recoveryChecker
  $recoveryCheckerArgs = @('-I', '-S', $recoveryChecker, '--manifest', $manifestAbsolute)
  if ($RuntimeRoot) { $recoveryCheckerArgs += @('--runtime-root', $DataRoot) }
  if ($PythonExecutable) { $recoveryCheckerArgs += @('--python-executable', $PythonExecutable) }
  foreach ($localRoot in $RecoveryLocalRoot) {
    Assert-SafeRecoveryLocalPath $localRoot
    $recoveryCheckerArgs += @('--approved-local-root', [IO.Path]::GetFullPath($localRoot))
  }
  $recoveryResult = & $recoveryPython @recoveryCheckerArgs
  if ($LASTEXITCODE -ne 0) { throw "SAFE_RECOVERY_PREFLIGHT_FAILED: no services started." }
  $recoveryStatus = $recoveryResult | ConvertFrom-Json
  if ($recoveryStatus.can_launch -ne $true) { throw "SAFE_RECOVERY_PREFLIGHT_FAILED: no services started." }
  if ($recoveryStatus.runtime_path_binding.path) {
    $bindingPath = [string]$recoveryStatus.runtime_path_binding.path
    Assert-SafeRecoveryLocalPath $bindingPath
    if (-not $bindingPath.StartsWith($DataRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "SAFE_RECOVERY_PATH_BINDING_OUTSIDE_RUNTIME" }
    $env:KQUANT_RUNTIME_PATH_BINDING = $bindingPath
    $env:KQUANT_RUNTIME_PATH_BINDING_SHA256 = [string]$recoveryStatus.runtime_path_binding.sha256
    $env:KQUANT_RUNTIME_DATA_ROOT = $DataRoot
  }
}
Set-Location $Root

function Get-KquantFileHash {
  param([string]$Path)
  $stream = [IO.File]::OpenRead($Path)
  $hasher = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
  finally { $stream.Dispose(); $hasher.Dispose() }
}

function Import-LocalEnv {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path -Encoding utf8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $name, $value = $line.Split("=", 2)
    $name = $name.Trim()
    if ($name -in @("KQUANT_RUNTIME_PATH_BINDING", "KQUANT_RUNTIME_PATH_BINDING_SHA256", "KQUANT_RUNTIME_DATA_ROOT")) { return }
    $value = $value.Trim().Trim('"').Trim("'")
    if ($name -and $value -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

if ($GatewayOnly -and $OptionsFoundation) { throw "GatewayOnly and OptionsFoundation cannot be used together." }
if ($TwoHourResearch -and -not $OptionsFoundation) { throw "TwoHourResearch requires the existing OptionsFoundation supervisor." }
if ($OneMinuteShadow -and -not $OptionsFoundation) { throw "OneMinuteShadow requires the existing OptionsFoundation supervisor." }
Import-LocalEnv (Join-Path $Root ".env")
$script:FoundationStage = 'PRIVATE_CONFIGURATION'
$loginFile = Join-Path $env:LOCALAPPDATA "KQUANT\workspace_login.dpapi"
if (Test-Path -LiteralPath $loginFile) {
  $loginSecure = ConvertTo-SecureString ([IO.File]::ReadAllText($loginFile))
  $loginBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($loginSecure)
  try {
    $loginConfig = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($loginBstr) | ConvertFrom-Json
    foreach ($name in @("KQUANT_WORKSPACE_LOGIN_ENABLED", "KQUANT_WORKSPACE_LOGIN_EMAIL", "KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", "KQUANT_WORKSPACE_SESSION_SECRET")) {
      [Environment]::SetEnvironmentVariable($name, [string]$loginConfig.$name, "Process")
    }
  } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($loginBstr) }
}
$marketFile = Join-Path $env:LOCALAPPDATA "KQUANT\longbridge_market.dpapi"
if ($OptionsFoundation -and (Test-Path -LiteralPath $marketFile)) {
  $marketSecure = ConvertTo-SecureString ([IO.File]::ReadAllText($marketFile))
  $marketBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($marketSecure)
  try {
    $marketConfig = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($marketBstr) | ConvertFrom-Json
    foreach ($name in @("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")) {
      if (-not [string]$marketConfig.$name) { throw "MARKET_CREDENTIAL_FIELD_MISSING" }
      [Environment]::SetEnvironmentVariable($name, [string]$marketConfig.$name, "Process")
    }
  } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($marketBstr) }
}
if (-not $OptionsFoundation) { Import-LocalEnv (Join-Path $CryptoRoot ".env") }
$env:KQUANT_GATEWAY_WEB_DIST = if ($UnifiedWebDist) { (Resolve-Path -LiteralPath $UnifiedWebDist).Path } else { Join-Path $Root "web\dist-unified" }
$env:KQUANT_BACKEND_RELEASE_ID = "UNVERIFIED_WORKING_TREE"
$env:KQUANT_BACKEND_MANIFEST_SHA256 = ""
$env:KQUANT_RUNTIME_MANIFEST = ""
$script:FoundationStage = 'RELEASE_VERIFICATION'
if ($RuntimeManifest) {
  $releasePath = (Resolve-Path -LiteralPath $RuntimeManifest).Path
  $release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
  foreach ($entry in $release.files.PSObject.Properties) {
    $source = [IO.Path]::GetFullPath((Join-Path $Root $entry.Name))
    if (-not $source.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Release source is outside workspace." }
    if ((Get-KquantFileHash $source) -ne $entry.Value.sha256) { throw "Release source hash mismatch: $($entry.Name)" }
  }
  if ($release.frontend -is [string] -and (Resolve-Path -LiteralPath $release.frontend).Path -ne $env:KQUANT_GATEWAY_WEB_DIST) { throw "Release/frontend pairing mismatch." }
  foreach ($section in @("retained_source_hashes", "frontend_files", "configuration_hashes", "source_fact_hashes")) {
    foreach ($entry in $release.$section.PSObject.Properties) {
      $artifact = [IO.Path]::GetFullPath((Join-Path $Root $entry.Name))
      if (-not $artifact.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Release artifact is outside workspace." }
      if ((Get-KquantFileHash $artifact) -ne $entry.Value) { throw "Release artifact hash mismatch: $($entry.Name)" }
    }
  }
  if ($release.dependency_versions) {
    $versions = $release.dependency_versions | ConvertTo-Json -Compress
    $encodedVersions = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($versions))
    $dependencyPython = if ($PythonExecutable) { $PythonExecutable } else { Join-Path $Root ".venv\Scripts\python.exe" }
    & $dependencyPython -c "import base64,json,sys; from importlib.metadata import version; expected=json.loads(base64.b64decode(sys.argv[1])); mismatches=[name for name,wanted in expected.items() if version(name)!=wanted]; sys.exit(1 if mismatches else 0)" $encodedVersions
    if ($LASTEXITCODE -ne 0) { throw "Release dependency version mismatch. Restore the declared local dependencies before starting." }
  }
  $env:KQUANT_BACKEND_RELEASE_ID = Split-Path -Leaf (Split-Path -Parent $releasePath)
  $env:KQUANT_BACKEND_MANIFEST_SHA256 = Get-KquantFileHash $releasePath
  $env:KQUANT_RUNTIME_MANIFEST = $releasePath
}
$env:KQUANT_CRYPTO_PORT = if ($env:KQUANT_CRYPTO_PORT) { $env:KQUANT_CRYPTO_PORT } else { "8010" }
$env:KQUANT_GATEWAY_PORT = if ($env:KQUANT_GATEWAY_PORT) { $env:KQUANT_GATEWAY_PORT } else { "8020" }
$env:KQUANT_GATEWAY_LAN_ADDRESS = ""
if ($LanAddress) {
  if ($env:KQUANT_WORKSPACE_LOGIN_ENABLED -ne "true" -or -not $env:KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH -or -not $env:KQUANT_WORKSPACE_SESSION_SECRET) { throw "Configure local login before LAN access." }
  $ipEntry = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $LanAddress -ErrorAction Stop
  $adapter = Get-NetAdapter -InterfaceIndex $ipEntry.InterfaceIndex -ErrorAction Stop
  if (-not $adapter.HardwareInterface -or $adapter.Status -ne "Up" -or "$($adapter.Name) $($adapter.InterfaceDescription)" -notmatch "WLAN|Wi-Fi|Wireless|802\.11") { throw "LAN address must belong to the active physical WLAN adapter." }
  $env:KQUANT_GATEWAY_LAN_ADDRESS = $LanAddress
}

if ($OptionsFoundation) {
  $foundationRoot = Join-Path $DataRoot "work\option_foundation\runtime"
  New-Item -ItemType Directory -Force -Path $foundationRoot | Out-Null
  $env:KQUANT_OPTION_RADAR_ENABLED = "true"
  $env:KQUANT_OPTION_RADAR_MODE = "foundation"
  $env:KQUANT_OPTION_TWO_HOUR_RESEARCH_ENABLED = if ($TwoHourResearch) { "true" } else { "false" }
  $env:KQUANT_OPTION_ONE_MINUTE_SHADOW_ENABLED = if ($OneMinuteShadow) { "true" } else { "false" }
  $env:KQUANT_OPTION_FOUNDATION_AUTO_PROBE = "true"
  $env:KQUANT_OPTION_FORWARD_PAPER_ENABLED = "false"
  $env:KQUANT_OPTION_FULL_WATCH_ENABLED = "true"
  $env:KQUANT_OPTION_FULL_WATCH_PROBE_COUNT = "8"
  $env:KQUANT_OPTION_FORWARD_PAPER_RUN_ID = "options-forward-20260920-01"
  $env:KQUANT_OPTION_FORWARD_PAPER_DB = Join-Path $DataRoot "work\options_forward_paper\options_forward_paper.sqlite3"
  $env:KQUANT_OPTION_FOUNDATION_ROOT = $foundationRoot
  $env:KQUANT_OPTIONS_PROFILE_CONFIG = Join-Path $Root "config\options_research_profiles_v1.json"
  $env:KQUANT_OPTION_CAPABILITY_EVIDENCE = if ($CapabilityEvidence) {
    (Resolve-Path -LiteralPath $CapabilityEvidence).Path
  } else {
    Join-Path $foundationRoot "latest_capability.json"
  }
  $env:KQUANT_GATEWAY_STOCKS_URL = "http://127.0.0.1:8001"
  $env:KQUANT_GATEWAY_CRYPTO_URL = "http://127.0.0.1:$($env:KQUANT_CRYPTO_PORT)"
}

if ($GatewayOnly) {
  $stockFallbackUrl = $null
  foreach ($candidatePort in @(8001, 8002)) {
    try {
      $candidateHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 2
      $candidateContract = [string]$candidateHealth.runtime.api_contract_version
      if (-not $stockFallbackUrl -and $candidateContract -like "kquant-api-*") {
        $stockFallbackUrl = "http://127.0.0.1:$candidatePort"
      }
      if ($candidateContract -eq "kquant-api-2026-09-14-options-tracking-v2") {
        $env:KQUANT_GATEWAY_STOCKS_URL = "http://127.0.0.1:$candidatePort"
        break
      }
    } catch { }
  }
  if (-not $env:KQUANT_GATEWAY_STOCKS_URL -and $stockFallbackUrl) {
    $env:KQUANT_GATEWAY_STOCKS_URL = $stockFallbackUrl
  }
  $cryptoGatewayReady = $false
  if ($env:KQUANT_GATEWAY_CRYPTO_URL) {
    try {
      $configuredHealth = Invoke-RestMethod -Uri "$($env:KQUANT_GATEWAY_CRYPTO_URL.TrimEnd('/'))/api/health" -TimeoutSec 2
      $cryptoGatewayReady = [string]$configuredHealth.api_contract_version -like "kquant-crypto-*"
    } catch { }
  }
  if (-not $cryptoGatewayReady) {
    foreach ($candidatePort in @([int]$env:KQUANT_CRYPTO_PORT, 8010, 8011) | Select-Object -Unique) {
      try {
        $candidateHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 2
        if ([string]$candidateHealth.api_contract_version -like "kquant-crypto-*") {
          $env:KQUANT_GATEWAY_CRYPTO_URL = "http://127.0.0.1:$candidatePort"
          $env:KQUANT_CRYPTO_PORT = [string]$candidatePort
          break
        }
      } catch { }
    }
  }
}

function New-ProcessToken {
  $bytes = New-Object byte[] 32
  $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
  return [Convert]::ToBase64String($bytes)
}

# These loopback-only tokens let the gateway share one browser session with
# both runtimes without copying a browser cookie into either backend. Always
# align inherited gateway aliases with the backend token so an old shell
# cannot create a split-brain local launch.
# Generate a fresh pair for every local stack launch. These are transport
# credentials between sibling processes, not user secrets; regenerating them
# prevents stale values inherited from an earlier PowerShell session from
# splitting the gateway and a backend into different trust domains.
if ($GatewayOnly) {
  if (-not $env:KQUANT_GATEWAY_STOCKS_API_TOKEN -and $env:KQUANT_API_AUTH_TOKEN) {
    $env:KQUANT_GATEWAY_STOCKS_API_TOKEN = $env:KQUANT_API_AUTH_TOKEN
  }
  if (-not $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN -and $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN) {
    $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN = $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN
  }
} else {
  $env:KQUANT_API_AUTH_TOKEN = New-ProcessToken
  $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN = New-ProcessToken
  $env:KQUANT_GATEWAY_STOCKS_API_TOKEN = $env:KQUANT_API_AUTH_TOKEN
  $env:KQUANT_GATEWAY_CRYPTO_API_TOKEN = $env:KQUANT_CRYPTO_INTERNAL_API_TOKEN
}

function Test-PythonExecutable {
  param([string]$Executable)
  if (-not $Executable) { return $false }
  try {
    & $Executable --version *> $null
    return $LASTEXITCODE -eq 0
  } catch { return $false }
}

function Resolve-Python {
  param([string]$ProjectRoot)
  if ($PythonExecutable) {
    if (-not (Test-PythonExecutable $PythonExecutable)) { throw "PINNED_PYTHON_UNAVAILABLE: no fallback permitted." }
    return $PythonExecutable
  }
  foreach ($candidate in @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv-win\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root ".venv-win\Scripts\python.exe")
  )) {
    if ((Test-Path -LiteralPath $candidate) -and (Test-PythonExecutable $candidate)) { return $candidate }
  }
  if (Test-PythonExecutable "python") { return "python" }
  throw "No usable Python was found. Create .venv and install the project dependencies first."
}

function Get-ListenerProcesses {
  param([int]$Port)
  try { $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop) }
  catch {
    if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound,*' -and
        $_.CategoryInfo.Category -eq 'ObjectNotFound') { return }
    throw
  }
  foreach ($listener in $listeners) {
    $process = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId = {0}' -f [int]$listener.OwningProcess) -OperationTimeoutSec 2 -ErrorAction Stop
    if ($process) {
      [pscustomobject]@{ Port = $Port; ProcessId = [int]$process.ProcessId; CommandLine = [string]$process.CommandLine }
    }
  }
}

function Stop-KquantListener {
  param($Listener)
  $command = $Listener.CommandLine.ToLowerInvariant()
  if ($command -notmatch "kquant|uvicorn") {
    throw "Port $($Listener.Port) is occupied by a non-KQUANT process (PID $($Listener.ProcessId)); startup stopped."
  }
  Write-Host "Stopping old KQUANT process PID $($Listener.ProcessId) on port $($Listener.Port)..." -ForegroundColor Yellow
  Stop-Process -Id $Listener.ProcessId -Force -ErrorAction SilentlyContinue
}

$ports = if ($GatewayOnly) {
  @([int]$env:KQUANT_GATEWAY_PORT)
} elseif ($OptionsFoundation) {
  @(8001, [int]$env:KQUANT_GATEWAY_PORT) | Select-Object -Unique
} else {
  @(8001, [int]$env:KQUANT_CRYPTO_PORT, [int]$env:KQUANT_GATEWAY_PORT) | Select-Object -Unique
}
$script:FoundationStage = 'PORT_AND_MUTEX'
if ($OptionsFoundation -and $KillExisting) { throw 'FOUNDATION_REQUIRES_EXPLICIT_IDENTITY_VERIFIED_STOP' }
foreach ($port in $ports) {
  foreach ($listener in @(Get-ListenerProcesses $port)) {
    if ($KillExisting) { Stop-KquantListener $listener }
    else { throw "Port $port is already in use. Re-run with -KillExisting to restart the unified workspace." }
  }
}
Start-Sleep -Milliseconds 500
if ($OptionsFoundation) {
  $script:FoundationMutex = New-Object System.Threading.Mutex($false, "Local\KQUANTOptionsFoundation8020")
  try { $ownsMutex = $script:FoundationMutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
  if (-not $ownsMutex) { throw "The existing Foundation launcher already owns this session." }
  $script:FoundationOwnsMutex = $true
}

$CryptoPython = Resolve-Python $CryptoRoot
$StockPython = if ($GatewayOnly) { $null } else { Resolve-Python $Root }
if ($OptionsFoundation -and $OneMinuteShadow) {
  if (Test-Path -LiteralPath $recoveryGate) {
    # Recheck the exact recovery receipts; never fall back to a missing legacy checker.
    if (-not $RecoveryManifest) { throw "SAFE_RECOVERY_REQUIRED: exact manifest missing before service start." }
    & $StockPython @recoveryCheckerArgs
  } else {
    $legacyDataChecker = Join-Path $Root "scripts\verify_runtime_data.py"
    Assert-SafeRecoveryLocalPath $legacyDataChecker
    if (-not (Test-Path -LiteralPath $legacyDataChecker)) { throw "RUNTIME_DATA_CHECKER_MISSING: no services started." }
    & $StockPython -B $legacyDataChecker
  }
  if ($LASTEXITCODE -ne 0) { throw "Existing research databases could not be verified. Startup cancelled; no empty database will be created." }
}
$LogRoot = Join-Path $DataRoot "work\logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
if ($OptionsFoundation) { Write-FoundationLifecycle "STARTING" "EXPLICIT_START" }

function Start-KquantService {
  param(
    [string]$Name,
    [string]$Python,
    [string]$Arguments,
    [string]$WorkingDirectory
  )
  $stdout = Join-Path $LogRoot "$Name.$($script:LaunchStamp).out.log"
  $stderr = Join-Path $LogRoot "$Name.$($script:LaunchStamp).err.log"
  $script:FoundationStage = 'START_' + $Name
  Write-Host "Starting $Name..." -ForegroundColor Cyan
  $process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
  $script:StartedServices += [pscustomobject]@{
    name = $Name
    pid = [int]$process.Id
    identity = Get-FoundationProcessIdentity ([int]$process.Id)
    executable = $Python
    arguments = $Arguments
    working_directory = $WorkingDirectory
    stdout = $stdout
    stderr = $stderr
  }
  if ($OptionsFoundation) { Write-FoundationLifecycle "SERVICE_STARTED" $Name ($script:StartedServices[-1].identity) }
}

if (-not $GatewayOnly) {
  $env:KQUANT_UNIFIED_UI_REDIRECT = "true"
  $env:KQUANT_UNIFIED_UI_URL = "http://127.0.0.1:$($env:KQUANT_GATEWAY_PORT)"
  $stockServiceName = if ($OptionsFoundation) { "stock-options-foundation" } else { "stock" }
  Start-KquantService $stockServiceName $StockPython "-m kquant.dashboard --host 127.0.0.1 --port 8001" $Root
  if (-not $OptionsFoundation) {
    Start-KquantService "crypto" $CryptoPython "-m kquant_crypto serve" $CryptoRoot
  }
}
$gatewayServiceName = if ($OptionsFoundation) { "gateway-options-foundation" } else { "gateway" }
Start-KquantService $gatewayServiceName $CryptoPython "-m kquant_crypto gateway" $CryptoRoot

if ($OptionsFoundation) {
  $serviceManifest = Join-Path $env:KQUANT_OPTION_FOUNDATION_ROOT "services.json"
  $startingSnapshot = [pscustomobject]@{
    launcher_pid = [int]$PID
    launcher_identity = $script:LauncherIdentity
    started_at = $script:LaunchStamp
    checked_at = [DateTimeOffset]::UtcNow.ToString("o")
    run_session_id = $script:RunSessionId
    system_boot = $script:SystemBoot
    state = "STARTING"
    backend_release = $env:KQUANT_BACKEND_RELEASE_ID
    backend_manifest_sha256 = $env:KQUANT_BACKEND_MANIFEST_SHA256
    mode = "options_foundation"
    launches = $script:StartedServices
    listeners = @()
    health_verified = $false
  }
  Write-FoundationJson $serviceManifest $startingSnapshot
}

function Wait-Healthy {
  param([string]$Url, [int]$Attempts = 30)
  for ($i = 0; $i -lt $Attempts; $i++) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
    } catch { }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

$gatewayUrl = "http://127.0.0.1:$($env:KQUANT_GATEWAY_PORT)/"
$script:FoundationStage = 'STARTUP_HEALTH'
if ($OptionsFoundation) {
  $foundationHealthy = (Wait-Healthy "http://127.0.0.1:8001/api/health/live") -and (Wait-Healthy $gatewayUrl)
} elseif ($GatewayOnly) {
  $foundationHealthy = Wait-Healthy "${gatewayUrl}api/gateway/health"
} else {
  $foundationHealthy = Wait-Healthy "${gatewayUrl}api/workspace/health"
}
if (-not $foundationHealthy) {
  Write-Host "The unified gateway did not respond. Check work\logs\gateway.err.log." -ForegroundColor Red
  throw "KQUANT workspace startup failed."
}

if ($OptionsFoundation) {
  $listenerServices = @()
  foreach ($definition in @(
    @{ port = 8001; role = "stock_backend"; expected = "kquant.dashboard" },
    @{ port = [int]$env:KQUANT_GATEWAY_PORT; role = "gateway"; expected = "kquant_crypto gateway" }
  )) {
    foreach ($listener in @(Get-ListenerProcesses $definition.port)) {
      $listenerServices += [pscustomobject]@{
        role = $definition.role
        port = [int]$definition.port
        pid = [int]$listener.ProcessId
        command_verified = $listener.CommandLine.ToLowerInvariant().Contains($definition.expected) -and (Test-FoundationOwnedProcess $listener.ProcessId)
        identity = Get-FoundationProcessIdentity $listener.ProcessId
      }
    }
  }
  $script:OwnedListenerIdentities = @($listenerServices | Where-Object command_verified | ForEach-Object { $_.identity })
  if ($listenerServices.Count -ne 2 -or ($listenerServices | Where-Object { -not $_.command_verified })) { throw 'STARTUP_LISTENER_OWNERSHIP_UNVERIFIED' }
}

Write-Host ""
Write-Host "KQUANT unified workspace is running" -ForegroundColor Green
Write-Host "Unified URL: $gatewayUrl" -ForegroundColor Green
if ($GatewayOnly) { Write-Host "Gateway-only mode: existing stock and Crypto services were left untouched." -ForegroundColor DarkGray }
if ($OptionsFoundation) {
  Write-Host "Options foundation mode: stock backend and gateway only; Crypto backend was not started." -ForegroundColor DarkGray
  Write-Host "Historical forward Paper policy retained; automatic Paper execution disabled" -ForegroundColor DarkGray
  Write-Host "Deterministic research signals enabled; account access, capital expansion, and orders disabled" -ForegroundColor DarkGray
  Write-Host "Capability evidence: $($env:KQUANT_OPTION_CAPABILITY_EVIDENCE)" -ForegroundColor DarkGray
  Write-Host "Service manifest: $serviceManifest" -ForegroundColor DarkGray
}
$stockFallback = if ($env:KQUANT_GATEWAY_STOCKS_URL) { $env:KQUANT_GATEWAY_STOCKS_URL } else { "http://127.0.0.1:8001" }
$cryptoFallback = if ($env:KQUANT_GATEWAY_CRYPTO_URL) { $env:KQUANT_GATEWAY_CRYPTO_URL } else { "http://127.0.0.1:$($env:KQUANT_CRYPTO_PORT)" }
Write-Host "Stock backend: $stockFallback/" -ForegroundColor DarkGray
Write-Host "Crypto backend: $cryptoFallback/" -ForegroundColor DarkGray
Write-Host "Unified frontend: $($env:KQUANT_GATEWAY_WEB_DIST)" -ForegroundColor DarkGray
Write-Host "Logs: work\logs" -ForegroundColor DarkGray
$loginStatus = "disabled (development mode)"
if ($env:KQUANT_WORKSPACE_LOGIN_ENABLED -eq "true") { $loginStatus = "email and password configured" }
Write-Host "Login: $loginStatus" -ForegroundColor DarkGray

if (-not $NoBrowser) { Start-Process $gatewayUrl }
Write-Host "Press Ctrl+C to stop this launcher; services log to work\logs." -ForegroundColor DarkGray
function Write-FoundationHeartbeat {
  param([string]$State)
  $observed = @()
  foreach ($definition in @(@{ port = 8001; expected = "kquant.dashboard" }, @{ port = [int]$env:KQUANT_GATEWAY_PORT; expected = "kquant_crypto gateway" })) {
    foreach ($listener in @(Get-ListenerProcesses $definition.port)) {
      $observed += [pscustomobject]@{ port = $definition.port; pid = $listener.ProcessId; identity = Get-FoundationProcessIdentity $listener.ProcessId; command_verified = $listener.CommandLine.ToLowerInvariant().Contains($definition.expected) -and (Test-FoundationOwnedProcess $listener.ProcessId) }
    }
  }
  $script:OwnedListenerIdentities = @($observed | Where-Object command_verified | ForEach-Object { $_.identity })
  $healthy = $false
  if ($State -eq "RUNNING" -and $observed.Count -eq 2 -and -not ($observed | Where-Object { -not $_.command_verified })) {
    try {
      $backend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/api/health/live" -TimeoutSec 2
      $gateway = Invoke-WebRequest -UseBasicParsing -Uri $gatewayUrl -TimeoutSec 2
      $healthy = $backend.StatusCode -eq 200 -and $gateway.StatusCode -eq 200
    } catch { }
  }
  $snapshot = [pscustomobject]@{ launcher_pid = [int]$PID; launcher_identity = $script:LauncherIdentity; run_session_id = $script:RunSessionId; system_boot = $script:SystemBoot; stage = $script:FoundationStage; started_at = $script:LaunchStamp; checked_at = [DateTimeOffset]::UtcNow.ToString("o"); mode = "options_foundation"; launches = $script:StartedServices; listeners = $observed; health_verified = $healthy; state = $State; exit_reason = $null; recovery_count = $recoveryCount; backend_release = $env:KQUANT_BACKEND_RELEASE_ID; backend_manifest_sha256 = $env:KQUANT_BACKEND_MANIFEST_SHA256; research_health_is_separate = $true }
  try {
    Write-FoundationJson $serviceManifest $snapshot
    $script:HeartbeatWriteFailures = 0
  } catch {
    $script:HeartbeatWriteFailures++
    Write-FoundationFailureFallback "DEGRADED" "HEARTBEAT_STORAGE_WRITE_FAILED"
    if ($script:HeartbeatWriteFailures -ge 3) { throw }
  }
}
$script:FoundationStage = 'MAIN_LOOP'
if ($OptionsFoundation -and (Invoke-FoundationMonitorCycle)) { Write-FoundationLifecycle "RUNNING" "STARTUP_HEALTH_VERIFIED" }
while ($true) {
  Start-Sleep -Seconds 10
  if (-not $OptionsFoundation) { continue }
  Invoke-FoundationMonitorCycle | Out-Null
}
} catch {
  $launcherExitReason = "LAUNCHER_ERROR_" + $_.Exception.GetType().Name
  $failureCode = 'EXCEPTION_' + $_.Exception.GetType().Name
  if ($_.Exception.Message -match '^([A-Z][A-Z0-9_]{4,80})(?=[:\s]|$)') { $failureCode = $Matches[1] }
  $details = [pscustomobject]@{ code = $failureCode; error_type = $_.Exception.GetType().Name;
    hresult = $_.Exception.HResult; script_line = $_.InvocationInfo.ScriptLineNumber;
    inner_error_type = $(if ($_.Exception.InnerException) { $_.Exception.InnerException.GetType().Name }) }
  if ($OptionsFoundation) { Write-FoundationLifecycle "FAILED" $launcherExitReason $details }
  # Exception text may contain private configuration. Emit only its type and stage.
  throw ('FOUNDATION_LAUNCH_FAILED_' + $script:FoundationStage + '_' + $_.Exception.GetType().Name)
} finally {
  if ($OptionsFoundation) {
    $terminalState = 'STOPPED'
    try { Stop-FoundationOwnedServices }
    catch { $terminalState = 'DEGRADED'; Write-FoundationFailureFallback 'DEGRADED' ('OWNED_PROCESS_CLEANUP_FAILED_' + $_.Exception.GetType().Name) }
    Write-FoundationTerminalSnapshot $terminalState $launcherExitReason
    Write-FoundationLifecycle 'EXITED' $launcherExitReason
    if ($script:FoundationMutex) { $script:FoundationMutex.Dispose() }
  }
}


