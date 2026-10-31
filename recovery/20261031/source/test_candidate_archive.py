"""Meaningful isolated fixtures for candidate packaging; no real cache is used."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

import pytest

import prepare_candidate_archive as archive
import build_candidate_archive_freeze as builder


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive.canonical(value) + b"\n")


def ref(root, path, name=None):
    row = {"source": path.relative_to(root).as_posix(), **archive.facts(path)}
    if name:
        row["archive"] = name
    return row


def make_page(task, error=None):
    return {"schema": archive.MINUTE_SCHEMA,
            "record_kind": "HISTORICAL_REDOWNLOAD_NOT_OLD_BUSINESS_RECOVERY",
            "task": task, "requested_at": "2026-10-07T07:00:00+00:00",
            "received_at": "2026-10-07T07:00:01+00:00",
            "rows": [{"open_at": "2026-10-06T13:30:00+00:00", "close": "1.00"}] if error is None else [],
            "validation": {"state": "PARTIAL"} if error is None else None,
            "error": error, "production_admission_verified": False,
            "provider_scope_sha256": "a" * 64, "old_business_continuity": "UNKNOWN"}


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    records = []
    for i, role in enumerate(sorted(archive.ROLES), start=1):
        path = root / "validated-snapshots/fixture" / (role + ".sqlite3")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE events (value TEXT)")
            db.executemany("INSERT INTO events(value) VALUES (?)", [(role,)] * i)
            db.commit()
            schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='events'").fetchone()[0]
            columns = [{"name": r[1], "type": r[2], "not_null": bool(r[3]), "pk_rank": r[5]}
                       for r in db.execute("PRAGMA table_info(events)")]
        records.append({"role": role, "recovery_state": "COMPLETE_VERIFIED",
            "snapshot_quick_check": ["ok"], "snapshot_integrity_check": ["ok"],
            "validated_snapshot": {"path": str(path), **archive.facts(path)},
            "schema_sha256": hashlib.sha256(json.dumps(schema, ensure_ascii=True).encode("ascii")).hexdigest(),
            "tables": [{"table": "events", "rows": i, "columns": columns, "sql": sql}],
            "selected_watermark_observations": [{"table": "events", "column": "rowid", "minimum": i, "rows": i}],
            "cross_store_continuity_confirmed": False})
    preparation = root / "evidence/preparation/receipt.json"
    write(preparation, {"schema": "KQUANT_LOCAL_RUNTIME_PREPARATION_V1",
        "status": "FOUR_PRESERVED_CANDIDATES_PREPARED_MINUTE_SCOPE_NOT_ACCEPTED",
        "all_original_main_wal_shm_unchanged": True, "original_database_opens": 0,
        "owner_acceptance_written": False, "production_started": False, "databases": records})
    cache = root / "minute-rebuild/fixture"
    pages = cache / "pages"
    pages.mkdir(parents=True)
    tasks, metadata, hashes = {}, {}, []
    for i in range(3):
        task = {"symbol": "TEST" + str(i), "provider_symbol": "TEST" + str(i) + ".US",
                "session": "2026-10-06", "expected_minutes": 390}
        task_id = hashlib.sha256(archive.canonical(task)).hexdigest()
        task["task_id"] = task_id
        if i == 2:
            tasks[task_id] = {"pages": [], "coverage": {"state": "QUOTA_DEFERRED"}}
            continue
        page = make_page(task, None if i == 0 else {"error_category": "HISTORY_MONTHLY_SYMBOL_QUOTA"})
        raw = archive.canonical(page)
        page_sha = hashlib.sha256(raw).hexdigest()
        (pages / (page_sha + ".json")).write_bytes(raw)
        metadata[page_sha] = {"provider_symbol": task["provider_symbol"], "requested_at": page["requested_at"],
                             "provider_scope_sha256": page["provider_scope_sha256"], "request_success": page["error"] is None}
        tasks[task_id] = {"pages": [page_sha], "coverage": {"state": "PARTIAL" if i == 0 else "ERROR"}}
        hashes.append(page_sha)
    index_path = cache / "coverage-index.json"
    write(index_path, {"schema": archive.MINUTE_SCHEMA, "tasks": tasks, "page_metadata": metadata,
                       "quota_blocks": [{"page_sha256": hashes[1], "provider_scope_sha256": "a" * 64}], "access_blocks": []})
    final = root / "evidence/minute-series/final.json"
    write(final, {"series_stop_reason": "QUOTA_ALLOWED_TASKS_VISITED", "production_started": False,
                  "old_business_continuity": "UNKNOWN", "coverage": {"PARTIAL": 1, "ERROR": 1, "QUOTA_DEFERRED": 1}})
    config = root / "development/workspace/config/policy.json"
    write(config, {"policy": "frozen fixture"})
    freeze = {"schema": archive.FREEZE_SCHEMA, "candidate_id": "fixture-p4-v1", "source_frozen": True,
              "minute_series_final": True, "preparation_receipt": ref(root, preparation),
              "minute_cache": {"index": ref(root, index_path), "series_final_receipt": ref(root, final)},
              "files": [ref(root, config, "source/config/policy.json")]}
    freeze_path = root / "evidence/freeze.json"
    write(freeze_path, freeze)
    return {"root": root, "freeze": freeze, "freeze_path": freeze_path, "records": records,
            "index": index_path, "pages": pages, "hashes": hashes, "preparation": preparation, "config": config}


def package(candidate):
    return archive.package(candidate["root"], "evidence/freeze.json")


def freeze_write(candidate):
    write(candidate["freeze_path"], candidate["freeze"])


def rewrite_zip(source, target, change):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, change(info.filename, src.read(info)))


def test_archive_restores_actual_four_snapshots_and_closed_pages_without_source_sqlite(candidate, monkeypatch):
    before = {r["role"]: archive.facts(Path(r["validated_snapshot"]["path"])) for r in candidate["records"]}
    connect = sqlite3.connect
    opened = []
    def restore_only(database, *args, **kwargs):
        assert "isolated-restore" in database
        assert "mode=ro&immutable=1" in database
        opened.append(database)
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(archive.sqlite3, "connect", restore_only)
    receipt = package(candidate)
    assert receipt["status"] == "ARCHIVED_AND_ISOLATED_RESTORE_VERIFIED_CANDIDATE_ONLY"
    assert len(opened) == 4
    assert receipt["all_frozen_sources_unchanged"] is True
    assert receipt["original_database_opens"] == receipt["source_sqlite_opens"] == 0
    assert receipt["owner_acceptance_written"] is False and receipt["can_launch"] is False
    assert receipt["old_business_continuity"] == "UNKNOWN"
    assert before == {r["role"]: archive.facts(Path(r["validated_snapshot"]["path"])) for r in candidate["records"]}
    report = json.loads(Path(receipt["restore_verification_path"]).read_bytes())
    assert all(r["integrity_check"] == ["ok"] and r["bytes_unchanged"] for r in report["stores"])
    assert {r["role"]: r["selected_watermarks"][0]["minimum"] for r in report["stores"]} == {
        r["role"]: r["selected_watermark_observations"][0]["minimum"] for r in candidate["records"]}
    summary = report["minute_cache"]
    assert summary["task_count"] == 3 and summary["page_count"] == 2 and summary["raw_row_count"] == 1
    assert summary["error_page_count"] == 1
    assert summary["cache_claimed_task_states"]["QUOTA_DEFERRED"] == 1
    assert summary["all_minutes_complete_claimed"] is False
    with zipfile.ZipFile(receipt["archive_path"]) as z:
        assert set(z.namelist()) == {"archive-manifest.json", "candidate-freeze.json",
            "evidence/local-preparation-receipt.json", "source/config/policy.json",
            "minute-cache/coverage-index.json", "minute-cache/series-final.json",
            *["preserved-stores/" + r + ".sqlite3" for r in archive.ROLES],
            *["minute-cache/pages/" + h + ".json" for h in candidate["hashes"]]}
        assert hashlib.sha256(z.read("archive-manifest.json")).hexdigest() == receipt["manifest_sha256"]


@pytest.mark.parametrize("field", ["source_frozen", "minute_series_final"])
def test_real_run_requires_both_explicit_freezes_before_output(candidate, field):
    candidate["freeze"][field] = False
    freeze_write(candidate)
    with pytest.raises(ValueError, match="EXPLICIT_SOURCE_AND_MINUTE_FREEZE_REQUIRED"):
        package(candidate)
    assert not (candidate["root"] / "evidence/candidate-packaging").exists()


@pytest.mark.parametrize("source", [".env", "development/workspace/config/secrets.json",
    "development/workspace/.venv/settings.json", "development/workspace/node_modules/package.json",
    "development/workspace/work/main.sqlite3", "recovered-data/business/old.sqlite3",
    "environment/wheels/sdk.whl", "../outside.json", "C:/secret.json", "config.json:secret", "\\server\\share\\x"])
def test_explicit_sources_reject_secret_dependency_old_live_or_escape_paths_before_open(candidate, source, monkeypatch):
    candidate["freeze"]["files"][0]["source"] = source
    freeze_write(candidate)
    original_safe = archive.safe
    def guarded_safe(root, rel, **kwargs):
        assert rel != source, "prohibited source must be rejected before filesystem access"
        return original_safe(root, rel, **kwargs)
    monkeypatch.setattr(archive, "safe", guarded_safe)
    with pytest.raises(ValueError):
        package(candidate)
    assert not (candidate["root"] / "evidence/candidate-packaging").exists()


def test_changed_explicit_source_does_not_use_old_hash(candidate):
    candidate["config"].write_bytes(b"changed config\n")
    with pytest.raises(ValueError, match="FROZEN_SOURCE_HASH_OR_SIZE_MISMATCH"):
        package(candidate)


def test_minute_page_tamper_rejected_before_archive(candidate):
    path = candidate["pages"] / (candidate["hashes"][0] + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="IMMUTABLE_MINUTE_PAGE_CHANGED"):
        package(candidate)


@pytest.mark.parametrize("mutation", ["metadata_orphan", "block_outside", "duplicate_task_page", "missing_page"])
def test_minute_index_page_and_block_closure_is_exact(candidate, mutation):
    index = json.loads(candidate["index"].read_bytes())
    first_task = next(k for k, v in index["tasks"].items() if v["pages"])
    if mutation == "metadata_orphan":
        index["page_metadata"]["0" * 64] = {}
    elif mutation == "block_outside":
        index["quota_blocks"][0]["page_sha256"] = "0" * 64
    elif mutation == "duplicate_task_page":
        index["tasks"][first_task]["pages"] *= 2
    else:
        sha = candidate["hashes"][0]
        index["tasks"][first_task]["pages"] = ["0" * 64]
        index["page_metadata"]["0" * 64] = index["page_metadata"].pop(sha)
    write(candidate["index"], index)
    candidate["freeze"]["minute_cache"]["index"] = ref(candidate["root"], candidate["index"])
    freeze_write(candidate)
    with pytest.raises(ValueError):
        package(candidate)


def test_page_task_binding_is_checked_even_with_matching_content_hash(candidate):
    old_sha = candidate["hashes"][0]
    page = json.loads((candidate["pages"] / (old_sha + ".json")).read_bytes())
    page["task"]["symbol"] = "OTHER"
    raw = archive.canonical(page)
    new_sha = hashlib.sha256(raw).hexdigest()
    (candidate["pages"] / (new_sha + ".json")).write_bytes(raw)
    index = json.loads(candidate["index"].read_bytes())
    task_id = page["task"]["task_id"]
    index["tasks"][task_id]["pages"] = [new_sha]
    index["page_metadata"][new_sha] = index["page_metadata"].pop(old_sha)
    write(candidate["index"], index)
    candidate["freeze"]["minute_cache"]["index"] = ref(candidate["root"], candidate["index"])
    freeze_write(candidate)
    with pytest.raises(ValueError, match="IMMUTABLE_MINUTE_PAGE_SCOPE_OR_TASK_INVALID"):
        package(candidate)


def test_snapshot_identity_companion_and_active_location_are_verified(candidate):
    path = Path(candidate["records"][0]["validated_snapshot"]["path"])
    Path(str(path) + "-wal").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="SNAPSHOT_COMPANIONS_FORBIDDEN"):
        package(candidate)


def test_restore_payload_sha_is_verified(candidate):
    receipt = package(candidate)
    source = Path(receipt["archive_path"])
    tampered = source.parent / "tampered.zip"
    rewrite_zip(source, tampered, lambda n, raw: b"X" + raw[1:] if n == "source/config/policy.json" else raw)
    with pytest.raises(ValueError, match="RESTORED_FILE_HASH_OR_SIZE_MISMATCH"):
        archive.verify_restore(tampered, source.parent / "tampered-restore", expected_manifest_sha256=receipt["manifest_sha256"])


@pytest.mark.parametrize("name", ["../outside.txt", "C:/outside.txt", "minute-cache/file.json:secret"])
def test_restore_rejects_unsafe_zip_members_before_destination(candidate, name):
    receipt = package(candidate)
    source = Path(receipt["archive_path"])
    tampered = source.parent / "unsafe.zip"
    rewrite_zip(source, tampered, lambda n, raw: raw)
    with zipfile.ZipFile(tampered, "a") as z:
        z.writestr(name, "blocked")
    destination = source.parent / "unsafe-restore"
    with pytest.raises(ValueError, match="UNSAFE_RELATIVE_PATH"):
        archive.verify_restore(tampered, destination, expected_manifest_sha256=receipt["manifest_sha256"])
    assert not destination.exists()


def test_restore_checks_logical_counts_even_when_payload_and_manifest_hashes_match(candidate):
    receipt = package(candidate)
    source = Path(receipt["archive_path"])
    with zipfile.ZipFile(source) as z:
        manifest = json.loads(z.read("archive-manifest.json"))
    manifest["stores"][0]["tables"][0]["rows"] += 100
    changed = archive.canonical(manifest) + b"\n"
    tampered = source.parent / "false-logical-proof.zip"
    rewrite_zip(source, tampered, lambda n, raw: changed if n == "archive-manifest.json" else raw)
    with pytest.raises(ValueError, match="RESTORED_SNAPSHOT_SCHEMA_ROWS_OR_INTEGRITY_MISMATCH"):
        archive.verify_restore(tampered, source.parent / "false-proof-restore",
                               expected_manifest_sha256=hashlib.sha256(changed).hexdigest())


@pytest.mark.parametrize("target", ["config", "index"])
def test_mid_packaging_source_change_retains_failure_receipt_and_never_verifies(candidate, monkeypatch, target):
    capture = archive.capture
    def race(root, freeze):
        values = capture(root, freeze)
        candidate[target].write_bytes(candidate[target].read_bytes() + b" ")
        return values
    monkeypatch.setattr(archive, "capture", race)
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_ZIP_STREAM|FROZEN_SOURCE_CHANGED_DURING_ARCHIVE"):
        package(candidate)
    receipts = list((candidate["root"] / "evidence/candidate-packaging").glob("*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_bytes())
    assert receipt["status"] == "FAILED_RETAIN_PARTIAL_ARCHIVE_FOR_REVIEW"
    assert receipt["isolated_restore_verified"] is False
    assert receipt["owner_acceptance_written"] is False


@pytest.fixture
def builder_inputs(candidate, monkeypatch):
    root = candidate["root"]
    (root / "development/workspace/pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    web_manifest = root / "development/workspace/web/dist-unified/manifest.webmanifest"
    write(web_manifest, {"name": "frozen fixture frontend"})
    browser_script = root / "development/workspace/scripts/check_r58_p9_browser.cjs"
    browser_script.parent.mkdir(parents=True, exist_ok=True)
    browser_script.write_text("// frozen browser check fixture\n", encoding="utf-8")
    credential_loader = root / "development/workspace/kquant/options_llm_credentials.py"
    credential_loader.parent.mkdir(parents=True, exist_ok=True)
    credential_loader.write_bytes((archive.ROOT / "development/workspace/kquant/options_llm_credentials.py").read_bytes())
    sensitive = root / "development/workspace/.env"
    sensitive.write_text("FIXTURE_MUST_NEVER_BE_READ=1\n", encoding="utf-8")
    for source in ("development/workspace/.venv/secret.json", "development/workspace/web/node_modules/package.json",
                   "development/workspace/.git/config.json", "development/workspace/cache/irrelevant.json"):
        write(root / source, {"excluded": True})
    write(root / "evidence/restore.md", {"fixture": "restore instructions"})
    (root / "build_candidate_archive_freeze.py").write_text("# fixture builder source\n", encoding="utf-8")
    monkeypatch.setattr(builder, "DEFAULT_EXTRAS", ["build_candidate_archive_freeze.py", "evidence/restore.md"])
    baselines = {}
    for i, name in enumerate(builder.BASELINES):
        path = root / "archives" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("isolated baseline fixture " + str(i)).encode("ascii"))
        baselines[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "purpose": "fixture only"}
    monkeypatch.setattr(builder, "BASELINES", baselines)
    database_paths = ["work/kquant_us.sqlite3", "work/options_full_watch/full_watch.sqlite3",
                      "work/options_one_minute/opening_trend_research.sqlite3",
                      "work/options_signal_copilot/signal_copilot.sqlite3"]
    active_facts = {}
    for record, local in zip(candidate["records"], database_paths):
        target = root / "development/workspace" / local
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record["validated_snapshot"]["path"], target)
        active_facts[local] = archive.facts(target)
    regression = root / "evidence/final-regression.json"
    write(regression, {"schema": "KQUANT_BACKEND_CANDIDATE_REGRESSION_V1",
        "status": "PASSED_TEST_SCOPE_AND_UNCHANGED_CANDIDATES", "source_hashes_unchanged": True,
        "candidate_database_hashes_unchanged": True, "production_started": False,
        "owner_acceptance_written": False, "provider_requests": 0,
        "source_inventory_after": {"config/policy.json": archive.facts(candidate["config"])},
        "candidate_databases_after": active_facts})
    candidate["regression"] = regression
    return candidate


def build_freeze(candidate, **overrides):
    arguments = {"candidate_id": "fixture-freeze-v1", "minute_final": "evidence/minute-series/final.json",
                 "regression_receipt": "evidence/final-regression.json", "destination": "evidence/built-freeze.json",
                 "preparation_receipt": "evidence/preparation/receipt.json",
                 "minute_index": "minute-rebuild/fixture/coverage-index.json",
                 "source_frozen": True, "minute_series_final": True}
    arguments.update(overrides)
    return builder.build(candidate["root"], **arguments)


def test_freeze_builder_rg_whitelist_excludes_credentials_dependencies_and_active_stores(builder_inputs, monkeypatch):
    original = archive.facts
    def refuse_sensitive_read(path):
        assert path.name != ".env"
        assert ".venv" not in path.parts and "node_modules" not in path.parts and ".git" not in path.parts
        return original(path)
    monkeypatch.setattr(archive, "facts", refuse_sensitive_read)
    result = build_freeze(builder_inputs)
    freeze = json.loads(Path(result["freeze_path"]).read_bytes())
    inventory = json.loads(Path(result["inventory_path"]).read_bytes())
    assert freeze["source_frozen"] is True and freeze["minute_series_final"] is True
    assert freeze["owner_acceptance_written"] is False and freeze["old_business_continuity"] == "UNKNOWN"
    sources = {r["source"] for r in freeze["files"]}
    assert "development/workspace/config/policy.json" in sources
    assert "development/workspace/pyproject.toml" in sources
    assert "development/workspace/web/dist-unified/manifest.webmanifest" in sources
    assert "development/workspace/scripts/check_r58_p9_browser.cjs" in sources
    assert "development/workspace/kquant/options_llm_credentials.py" in sources
    assert "evidence/built-freeze-inventory.json" in sources
    assert not any("/.env" in s or "/work/" in s or "node_modules" in s or ".venv" in s for s in sources)
    assert any(r["source"].endswith("/.env") for r in inventory["excluded_candidates"])
    assert inventory["environment_wheels_duplicated"] is False
    assert all(r["included_in_candidate_archive"] is False for r in freeze["external_baselines"])
    assert freeze["pinned_sdk_requirement"]["wheel_in_candidate_archive"] is False
    # Feed the generated explicit whitelist through the actual packager too.
    receipt = archive.package(builder_inputs["root"], "evidence/built-freeze.json")
    assert receipt["isolated_restore_verified"] is True


@pytest.mark.parametrize("field", ["source_frozen", "minute_series_final"])
def test_freeze_builder_requires_parent_freezes_before_any_source_scan(builder_inputs, monkeypatch, field):
    monkeypatch.setattr(builder, "workspace_listing", lambda root: pytest.fail("must not scan before caller freeze"))
    with pytest.raises(ValueError, match="EXPLICIT_FINAL_SOURCE_AND_MINUTE_FREEZE_REQUIRED"):
        build_freeze(builder_inputs, **{field: False})
    assert not (builder_inputs["root"] / "evidence/built-freeze.json").exists()


def test_freeze_builder_rechecks_current_source_against_final_regression(builder_inputs):
    builder_inputs["config"].write_bytes(b"changed after final tests")
    with pytest.raises(ValueError, match="SOURCE_CHANGED_AFTER_FINAL_BACKEND_REGRESSION"):
        build_freeze(builder_inputs)
    assert not (builder_inputs["root"] / "evidence/built-freeze.json").exists()


def test_freeze_builder_refuses_overwrite_and_wrong_baseline_hash(builder_inputs):
    baseline = builder_inputs["root"] / "archives" / next(iter(builder.BASELINES))
    baseline.write_bytes(b"wrong baseline")
    with pytest.raises(ValueError, match="ORIGINAL_CLOUD_BASELINE_BYTE_HASH_MISMATCH"):
        build_freeze(builder_inputs)
    output = builder_inputs["root"] / "evidence/built-freeze.json"
    output.write_bytes(b"already exists")
    with pytest.raises(ValueError, match="EXISTING_FREEZE_OR_INVENTORY_NO_OVERWRITE"):
        build_freeze(builder_inputs)
    assert output.read_bytes() == b"already exists"


def test_credential_source_exception_requires_exact_reviewed_bytes_and_path(builder_inputs):
    path = builder_inputs["root"] / "development/workspace/kquant/options_llm_credentials.py"
    path.write_bytes(b"# changed credential-loader bytes are not allowed\n")
    with pytest.raises(ValueError, match="PINNED_CREDENTIAL_LOADER_SOURCE_CHANGED"):
        build_freeze(builder_inputs)
    assert not (builder_inputs["root"] / "evidence/built-freeze.json").exists()
    assert archive.is_secret_or_dependency("development/workspace/config/credentials.py") is True
    assert archive.is_secret_or_dependency("development/workspace/kquant/options_llm_credentials.json") is True
