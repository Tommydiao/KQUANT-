# Contributing to KQUANT

Thanks for your interest in KQUANT. The project is a **research-only quantitative research platform**. Contributions are welcome when they preserve reproducibility, transparent evidence, and the strict separation between research and trade execution.

## Ground rules

- KQUANT must remain research-only and read-only with respect to brokers, exchanges and wallets.
- Do not add order placement, account trading, private-key signing or automated execution paths.
- AI/LLM output is advisory. Deterministic validation and safety gates remain authoritative.
- Do not commit credentials, API keys, account data, private market data or personally identifiable information.
- New market-data integrations must expose provenance, timing, freshness and failure states rather than silently substituting data.

## Development setup

### US stock terminal

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
cd web
npm ci
npm run build
cd ..
.\start_kquant_stock_terminal.ps1 -KillExisting
```

### Crypto terminal

```powershell
cd crypto
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m kquant_crypto db migrate
.\.venv\Scripts\python.exe -m pytest -q
cd web
npm ci
npm run build
```

## Before opening a pull request

Run the checks relevant to your change. For cross-cutting changes, run all of them.

```powershell
# Root / US stocks
python -m pytest -q
cd web
npm test -- --run
npm run build
cd ..
python scripts/scan_tracked_secrets.py
python scripts/verify_read_only_boundary.py

# Crypto
cd crypto
python -m pytest -q
cd web
npm test -- --run
npm run build
cd ..
python scripts/scan_tracked_secrets.py --root .
python scripts/verify_read_only_boundary.py
```

GitHub Actions repeats the main verification suites on pull requests.

## Pull request expectations

A good PR should:

1. Explain the research problem or engineering issue being solved.
2. Describe any changes to data provenance, validation rules, safety boundaries or public APIs.
3. Include tests for new behavior and regression coverage for bug fixes.
4. Update documentation when setup, APIs, schemas or user-visible behavior changes.
5. Keep changes focused. Large architectural changes should start with an issue or discussion first.

## Data and model contributions

When adding a factor, strategy, model or evaluation rule:

- define the input data and time boundary;
- prevent look-ahead leakage;
- state how missing or stale evidence is handled;
- keep deterministic calculations separate from generated explanations;
- include reproducible validation or synthetic fixtures where practical;
- do not present backtests as evidence of future returns.

## Security issues

Please do not open a public issue for a suspected vulnerability. Follow [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under the repository's [MIT License](LICENSE).
