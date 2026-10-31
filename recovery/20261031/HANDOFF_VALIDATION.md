# Code Handoff Validation

Validated in the independent checkout `KQUANT-GitHub-Handoff-20261031`, not the
original runtime workspace. The export does not modify accepted code or business data.

- 1,297 exported source/config/build/report files; 30,632,487 uncompressed bytes.
- 650 Python files parsed without importing production modules.
- All 93 latest development source/build/config identity entries matched their
  original SHA-256. This is not a runtime release identity.
- 49 isolated tests passed in 14.21 seconds after moving to the export directory.
  See `HANDOFF_TESTS.xml`. One existing Starlette/AnyIO deprecation warning remains.
- Tests cover the read-only AI client, budget, sidecar, authenticated route,
  HTTP attribution and literal-loopback transport. Test inputs are synthetic.
- No SDK or real model request, database recovery, production start, matched-hour
  performance acceptance or natural signal acceptance was performed for this upload.
- Latest documented runtime sample is 2026-10-31T15:30:07Z. It is a historical
  sample, not a promise that the service remains online/offline after that instant.

## Public Export Boundaries

`HANDOFF_FILES.json` records original and exported hashes. One historical XML
failure trace contains a bearer-shaped value; the public copy is redacted and has
a different export hash. Historical failures are not removed or changed to PASS.
24 source-level literal findings were reviewed as explicit synthetic/test fixtures,
including `TEST_ONLY`, `SHOULD_NOT_CAPTURE` and test-only password examples.

`EXCLUSIONS.json` lists 187 excluded files/subtrees. Directory exclusions describe
the entire subtree; private subtrees are not enumerated or opened for this export.
Raw historical logs/evidence, proprietary raw market samples, credentials, DPAPI,
browser data, all SQLite databases/sidecars, dependencies and caches are excluded.
Six explicitly TEST_ONLY topology summary reports are included as exceptions to
the raw evidence exclusion. Referenced raw logs and databases remain on the old PC.

This is a code handoff, not the full private audit pack, a business-data backup,
or proof that every historical evidence reference is self-contained on GitHub.
Missing original evidence remains missing on a new machine until separately restored.

Observed development environment: Python 3.12.10, Longbridge 4.4.1, Node v24.14.0.
Python package versions are in `requirements-observed.txt`; npm versions are locked
in the original `package-lock.json`. Rebuild environments; do not copy `.venv`.

The repository keeps byte-exact line endings for this handoff so hash verification
works across fresh clones. Do not rewrite historical manifests to make a new machine
appear to have the old machine's accepted identity.
