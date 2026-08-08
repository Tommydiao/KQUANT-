# v0.9.0-personal-rc1 Release Candidate

## Included Scope

- Local stock-only research dashboard with a first-screen Today decision state.
- Data caution, offline, stale, AI unavailable, market regime, and `NO TRADE`
  states rendered before manual-review candidates.
- Decision Ledger, manual Journal, forward-observation protocol, and cash-only
  paper simulation ledger.
- Security headers, local-only default CORS, optional API authentication,
  bounded API rate limiter, secret/route scanner, backup and restore drill.
- PWA manifest and service worker that deliberately does not cache API data.

## Release Gate

Run:

```powershell
.\scripts\verify_release_candidate.ps1
```

The command runs Python tests, the read-only route audit, security scan, and
frontend lint/test/build. A release is not green until all commands finish
successfully.

## Rollback

1. Stop the local dashboard.
2. Restore a verified SQLite backup to an explicit replacement path.
3. Run `python -m kquant restore-drill --backup-path <backup>` first.
4. Restart the previous tagged build and verify `/api/health` plus the
   read-only route scan.

This release candidate does not approve real-money activity. Day 84 remains a
gated report whose default decision is `NO_GO` until real forward evidence
exists.
