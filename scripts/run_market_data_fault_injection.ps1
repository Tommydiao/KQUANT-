param(
    [string]$Python = ".venv\\Scripts\\python.exe"
)

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found: $Python"
}

& $Python -m pytest tests/test_market_data_fault_injection.py -q
exit $LASTEXITCODE
