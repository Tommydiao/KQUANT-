# OSS Publication Checklist

Use this checklist before submitting KQUANT to programs that require a public open-source repository.

## Repository settings

### Visibility

Change the repository from **Private** to **Public** only after reviewing the full history for secrets, private datasets, customer/company material and credentials.

Before changing visibility, run:

```powershell
python scripts/scan_tracked_secrets.py
cd crypto
python scripts/scan_tracked_secrets.py --root .
```

Also review Git history manually for files that may have been deleted from the current tree but remain in history.

### Description

Recommended GitHub repository description:

> Research-only quantitative platform for US equities and crypto with deterministic validation, data-trust gates, and advisory AI agents.

### Topics

Recommended topics:

- `quantitative-finance`
- `quant-research`
- `ai-agent`
- `algorithmic-trading`
- `crypto`
- `backtesting`
- `llm`
- `market-data`
- `python`
- `research`

`algorithmic-trading` is included for discoverability, but KQUANT itself remains research-only and does not submit trades.

## Community files

- [x] `LICENSE`
- [x] `CONTRIBUTING.md`
- [x] `SECURITY.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `ROADMAP.md`
- [x] OSS landing-page README
- [x] Architecture diagram
- [x] CI / Python / License badges
- [x] Explicit Research Only / No Automated Trading statement

## Security settings

After the repository is public:

1. Open **Settings → Security**.
2. Enable private vulnerability reporting if available.
3. Confirm Dependabot/security alerts according to your preferred maintenance workflow.
4. Never publish real provider credentials in issues, Actions logs or screenshots.

## First public release

The root package already declares version `0.2.0`, so the first OSS release should be **v0.2.0**, not v0.1.0.

After the OSS hardening PR is merged and CI is green:

1. Open **Releases → Draft a new release**.
2. Create tag `v0.2.0` from `main`.
3. Release title: `KQUANT v0.2.0 — OSS Baseline`.
4. Copy the body from `docs/releases/v0.2.0.md`.
5. Do not mark it as a pre-release unless you intentionally want a pre-release lifecycle.
6. Publish only after checking that the public repository contains no secrets or private data.

## Roadmap issues

Create a small number of concrete issues tied to `ROADMAP.md` rather than dozens of placeholder issues. Good first issues should have a clear problem statement, acceptance criteria and explicit safety/non-goal notes.

## Final pre-application check

Before submitting an OSS-program application, verify that a logged-out visitor can see:

- repository description and topics;
- MIT license;
- passing CI badge;
- README architecture and quick start;
- contribution/security docs;
- at least a few real roadmap issues;
- the `v0.2.0` release;
- recent maintenance activity.
