# Hybrid M0/M1 Verified Runbook

## Environment and Boundaries

Working directory: `C:\Users\Administrator\Desktop\KQUANT-\crypto`.
Verified interpreter:
`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`.
No new dependency installed and no shared venv mutated. New modules use standard
library; audit replay reuses existing DuckDB. For later model dependencies, build
a separate pinned environment, never pip-upgrade the collector environment.

Important: bare script-context editable discovery still points to the older
Desktop/KQUANT-CRYPTO checkout. The verified cwd `python -m pytest` uses this
repo (pytest pythonpath="."); the candidate CLI/verifier explicitly prepend ROOT.
Do not use the installed `kquant-crypto` console command for this milestone.
Validate __file__ before any future launch; the audit records both resolutions.

M0/M1 needs local file reads plus write permission only to NEW hybrid output
directories and pytest temporary files. No API key, paid model, source purchase,
account privilege or notification delivery is required. Never print .env or
private credentials. Credentials/source authorization and fee budget for later
LLM stages remain unapproved; do not configure them implicitly.

## Actually Executed Commands

```powershell
Set-Location 'C:\Users\Administrator\Desktop\KQUANT-\crypto'
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q
```

Final code:539 passed in64.92s, exit0. Full log in
`outputs/hybrid_regime_v1/full_regression_final_20260905.txt`.
The final focused48 Hybrid tests passed in0.68s, exit0, with
`contract_tests_final_20260905.txt` as the log.

```powershell
python scripts/audit_hybrid_baseline.py --output outputs/hybrid_regime_v1/m0_inventory_20260905_01
python scripts/verify_hybrid_baseline.py --output outputs/hybrid_regime_v1/m0_golden_20260905_04
```

Both executed exit0. These output directories already exist and MUST NOT be
reused: choose a new audit ID to rerun. The scripts deliberately fail instead of
overwriting. Audit reads candidate SQLite via mode=ro/query_only. Golden verifier
checks complete file bytes for integrity but filters development rows before
materialization. No model training and no old evidence writes.

`git diff --check` executed at repository root, exit0. The preserved dirty work
is not a new commit; no reset, stash, checkout or blanket staging is appropriate.

## Start / Status / Stop / Recovery

No Hybrid market runtime or forward/start/stop CLI exists in M0/M1. Do NOT infer
that these commands are ready from the master plan. ContractWriter is a synthetic
fixture, not a service. `hybrid_candidate_v1.sqlite3` is not created.

Original collector40088/36116 and candidate31772 remain their current owners.
Do not send their stop markers, acquire their leases or restart their web stack.
Status investigation uses process listing and the read-only audit only. The
candidate itself continues to update its own DB; changing live counts are normal.

Synthetic restoration is tested with isolated temporary SQLite and the same
committed intent/fill ID. A writer callback failure halts the fixture; protection
events remaining in memory are explicitly not a production recovery mechanism.
M5 must implement stop-new-entries, drain and explicit force-stop separately.

## Interpretation

Historical OHLC is a proxy, current exchange filters are not historical filters,
and exposed development history is not unseen OOS. M0 source/contract test PASS
does not satisfy the model, data, performance or original execution admission
Gates. The immutable contract config has all activation flags false and unresolved
prior/MC/10R fields null. Read HYBRID_BLOCKERS_V1_1.md before downstream work.
