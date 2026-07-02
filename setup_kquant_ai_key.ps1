param(
  [string]$ReviewModel = "gpt-5.4",
  [string]$BatchModel = "gpt-5.4-mini",
  [string]$DeepModel = "gpt-5.5",
  [string]$ResearchModel = "gpt-5.5-pro"
)

$ErrorActionPreference = "Stop"

Write-Host "KQUANT AI Review local setup" -ForegroundColor Cyan
Write-Host "This stores the OpenAI key in your Windows user environment only." -ForegroundColor DarkGray
Write-Host "Do not put this key in GitHub, Vercel frontend variables, screenshots, or chat." -ForegroundColor Yellow

$secure = Read-Host "Paste new OPENAI_API_KEY" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
  if ($bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

if (-not $key -or -not $key.Trim()) {
  throw "OPENAI_API_KEY was empty. Nothing changed."
}

[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $key.Trim(), "User")
[Environment]::SetEnvironmentVariable("KQUANT_AI_REVIEW_MODEL", $ReviewModel, "User")
[Environment]::SetEnvironmentVariable("KQUANT_AI_BATCH_MODEL", $BatchModel, "User")
[Environment]::SetEnvironmentVariable("KQUANT_AI_DEEP_MODEL", $DeepModel, "User")
[Environment]::SetEnvironmentVariable("KQUANT_AI_RESEARCH_MODEL", $ResearchModel, "User")

$env:OPENAI_API_KEY = $key.Trim()
$env:KQUANT_AI_REVIEW_MODEL = $ReviewModel
$env:KQUANT_AI_BATCH_MODEL = $BatchModel
$env:KQUANT_AI_DEEP_MODEL = $DeepModel
$env:KQUANT_AI_RESEARCH_MODEL = $ResearchModel

Write-Host "Saved AI Review environment variables for this Windows user." -ForegroundColor Green
Write-Host "Next daily startup: double-click KQUANT_START.cmd or run .\KQUANT_START.cmd" -ForegroundColor Green
