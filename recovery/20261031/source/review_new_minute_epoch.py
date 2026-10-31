"""Produce actual read-only epoch precheck and a proposal, without an acceptance."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).absolute().parent
OUT = ROOT / "evidence/new-minute-epoch-review-20261007-v1"
PREPARATION = ROOT / "evidence/local-runtime-preparation-20261007T071740946787Z-pid11156"
RUNTIME = ROOT / "development/workspace"
EXPECTED_SCHEMA = "1ccfbb3927e1a65a2f8ae01252fcbf97402deb30b4f51d64d4da8e023bc22b8a"


def safe(path):
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(ROOT) or ":" in str(path)[2:]:
        raise ValueError("OUTSIDE_REVIEW_ROOT_OR_ADS")
    for item in [path, *path.parents]:
        try:
            value = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_OR_LINK_DENIED")
    return path


def metadata(path):
    path = safe(path)
    value = path.stat()
    return {"path": str(path), "bytes": value.st_size, "mtime_ns": value.st_mtime_ns,
            "file_identity": {"device": value.st_dev, "inode": value.st_ino}}


def facts(path):
    path = safe(path)
    before = metadata(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if metadata(path) != before:
        raise ValueError("REVIEW_SOURCE_CHANGED_DURING_READ")
    return {**before, "sha256": digest}


def absence(target):
    return {str(safe(Path(str(target) + suffix))): not Path(str(target) + suffix).exists()
            for suffix in ("", "-wal", "-shm", "-journal", ".preparing")}


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with safe(path).open("xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


WORKER = r'''
import importlib.util, json, pathlib, sys
sys.dont_write_bytecode = True
request=json.loads(sys.stdin.buffer.read(65537))
counters={"sqlite_connection_attempts":0,"env_file_open_attempts":0,"network_attempts":0,"sdk_or_business_import_attempts":0}
def audit(event,args):
 if event=="sqlite3.connect":
  counters["sqlite_connection_attempts"]+=1
  raise RuntimeError("DB_CONNECTION_FORBIDDEN_IN_ACTUAL_PRECHECK")
 if event=="open" and isinstance(args[0],(str,bytes)) and pathlib.Path(args[0].decode(sys.getfilesystemencoding(),"surrogateescape") if isinstance(args[0],bytes) else args[0]).name.lower().startswith(".env"):
  counters["env_file_open_attempts"]+=1
  raise RuntimeError("ENV_FILE_FORBIDDEN_IN_ACTUAL_PRECHECK")
 if event=="socket.connect":
  counters["network_attempts"]+=1
  raise RuntimeError("NETWORK_FORBIDDEN_IN_ACTUAL_PRECHECK")
 if event=="import" and args and isinstance(args[0],str) and args[0].split(".")[0] in {"longbridge","dotenv","kquant"}:
  counters["sdk_or_business_import_attempts"]+=1
  raise RuntimeError("SDK_BUSINESS_IMPORT_FORBIDDEN_IN_ACTUAL_PRECHECK")
sys.addaudithook(audit)
for name,path in [("cloud_archive_inventory",request["inventory_module"]),("actual_scope_precheck_new_data_epoch",request["epoch_module"])]:
 spec=importlib.util.spec_from_file_location(name,path)
 module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
result=module.check(request["declaration"],None,roots=[pathlib.Path(request["root"])],allow_test_only=False)
print(json.dumps({"actual_check_result":result,"guard_counters":counters,"acceptance_argument":None,"allow_test_only":False,"site_disabled":sys.flags.no_site,"isolated":sys.flags.isolated,"bytecode_writes_disabled":sys.dont_write_bytecode}))
'''


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    materials = [
        Path(__file__), PREPARATION / "receipt.json", PREPARATION / "new-minute-epoch-declaration-proposed.json",
        PREPARATION / "minute-schema.sql", RUNTIME / "kquant/options_one_minute.py",
        RUNTIME / "kquant/recovery_activation.py", RUNTIME / "scripts/record_recovery_activation.py",
        ROOT / "prepare_local_runtime.py", ROOT / "development/handoff/tools/new_data_epoch.py",
        ROOT / "development/handoff/tools/cloud_archive_inventory.py",
        ROOT / "evidence/minute-audits/20261007T081016463042Z-2bf68ba161b03909b830e0417d5aea1e0557e8e72c81ce9bc5c545437f81d627.json",
        ROOT / "evidence/clock-diagnosis-20261007T094313248500Z-cc2568a3f904c424a582fa8a471c2a104e3dcdbb24fe18643277a94aa62499e4.json",
    ]
    before = {str(path): facts(path) for path in materials}
    preparation = json.loads((PREPARATION / "receipt.json").read_bytes())
    declaration = json.loads((PREPARATION / "new-minute-epoch-declaration-proposed.json").read_bytes())
    source = (RUNTIME / "kquant/options_one_minute.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    schema = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(name, ast.Name) and name.id == "SCHEMA" for name in node.targets))
    literal_sha = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    if (literal_sha != EXPECTED_SCHEMA or literal_sha != declaration["schema_sha256"]
            or (PREPARATION / "minute-schema.sql").read_bytes() != schema.encode("utf-8")):
        raise ValueError("ACTUAL_SOURCE_SCHEMA_PROPOSAL_MISMATCH")
    target = safe(Path(declaration["minute_path"]))
    target_before = absence(target)
    if not all(target_before.values()):
        raise ValueError("PROPOSED_MINUTE_TARGET_OR_COMPANION_NOT_ABSENT")
    stores = []
    large_before = {}
    for row in preparation["databases"]:
        store = {"role": row["role"], "recovery_state": row["recovery_state"], "old_business_continuity": "UNKNOWN",
                 "existing_recovery_receipt": row["receipt"], "selected_watermark_observations": row["selected_watermark_observations"]}
        for key in ("validated_snapshot", "active_candidate"):
            anchored = row[key]
            observed = metadata(Path(anchored["path"]))
            if any(observed[field] != anchored[field] for field in ("bytes", "mtime_ns", "file_identity")):
                raise ValueError("EXISTING_PRESERVED_CANDIDATE_METADATA_CHANGED")
            large_before[anchored["path"]] = observed
            store[key] = {**observed, "prior_verified_sha256": anchored["sha256"],
                          "prior_sha_anchor": str(PREPARATION / "receipt.json"),
                          "sha_recomputed_this_precheck": False, "sqlite_opened_this_precheck": False}
        stores.append(store)
    worker_request = {"root": str(ROOT), "declaration": declaration,
                      "inventory_module": str(ROOT / "development/handoff/tools/cloud_archive_inventory.py"),
                      "epoch_module": str(ROOT / "development/handoff/tools/new_data_epoch.py")}
    process = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", WORKER],
                             input=json.dumps(worker_request).encode("ascii"), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=10, check=False,
                             env={"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows"},
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise ValueError("ISOLATED_ACTUAL_PRECHECK_WORKER_FAILED")
    observed = json.loads(process.stdout)
    result = observed["actual_check_result"]
    codes = [row["code"] for row in result["errors"]]
    if codes != ["EXACT_DATA_SCOPE_ACCEPTANCE_REQUIRED"] or result["database_creation_allowed"] or result["can_launch"]:
        raise ValueError("EXPECTED_ACTUAL_NONE_ACCEPTANCE_DENIAL_NOT_OBSERVED")
    if any(observed["guard_counters"].values()):
        raise ValueError("PRECHECK_SIDE_EFFECT_ATTEMPT_DETECTED")
    after = {str(path): facts(path) for path in materials}
    large_after = {path: metadata(Path(path)) for path in large_before}
    target_after = absence(target)
    if before != after or large_before != large_after or target_before != target_after:
        raise ValueError("ACTUAL_PRECHECK_INPUTS_OR_TARGET_CHANGED")
    scope = {
        "candidate_id": "r58-p10-resume-20261007-7ff4101a4962ecc1", "declaration": declaration,
        "proposed_session_only": "2026-10-07", "runtime_root": str(RUNTIME), "minute_target": str(target),
        "first_actual_session_requires_recheck_before_acceptance": True,
        "literal_schema_sha256": literal_sha, "actual_sqlite_master_schema_sha256": None,
        "schema_not_executed": True, "preserved_stores": stores,
        "historical_scope": {"from_session": "2026-09-09", "to_session": "2026-10-06", "mapped_assets": 100,
                             "unconfirmed_no_query_assets": 11, "accepted_unique_minutes": 778771,
                             "theoretical_slots": 780000, "missing_slots": 1229,
                             "history_only_not_live_current_minutes": True, "production_admission_verified": False},
        "data_scope_acceptance": None, "owner_acceptance_written": False,
        "old_business_continuity": "UNKNOWN", "old_position_continuity": "UNKNOWN",
        "database_creation_allowed": False, "database_created": False,
        "production_started": False, "execution_enabled": False, "qualified_signal_authorized": False,
        "complete_restoration_claimed": False, "can_launch": False,
    }
    value = {"schema": "KQUANT_ACTUAL_NEW_EPOCH_PRECHECK_V1", "status": "ACTUAL_NONE_ACCEPTANCE_DENIED_SCOPE_DECISION_REQUIRED",
             "observed_at_untrusted_host_utc": datetime.now(timezone.utc).isoformat(), "host_clock_precision_verified": False,
             "actual_worker": observed, "scope_proposal": scope,
             "small_source_material_sha_before": before, "small_source_material_sha_after": after,
             "small_source_sha_and_identity_unchanged": True,
             "large_candidate_metadata_before": large_before, "large_candidate_metadata_after": large_after,
             "large_candidate_metadata_unchanged": True,
             "large_candidate_sha_recomputed": False, "original_database_opens": 0, "candidate_database_opens": 0,
             "sdk_imports": 0, "provider_requests": 0, "env_file_reads": 0,
             "target_and_companions_absent_before": target_before, "target_and_companions_absent_after": target_after,
             "minute_created": False, "activation_receipts_produced": False,
             "owner_acceptance_written": False, "production_started": False, "can_launch": False}
    write_new(OUT / "DECLARATION_PROPOSAL.json", declaration)
    with (OUT / "minute-schema.sql").open("xb") as handle:
        handle.write(schema.encode("utf-8"))
    digest = write_new(OUT / "ACTUAL_NEW_EPOCH_PRECHECK.json", value)
    text = f"""# 实际新分钟库范围审阅材料

候选 r58-p10-resume-20261007-7ff4101a4962ecc1；本文件是工程审阅提案，不是 OWNER 接受或生产激活。

实际隔离调用 `new_data_epoch.check(当前实际声明, None, allow_test_only=False)` 的唯一拒绝码为 **EXACT_DATA_SCOPE_ACCEPTANCE_REQUIRED**。使用 -I -S -B、只加载两份移交标准库工具，DB/env/network/SDK/业务模块审计钩子均为零；没有创建分钟库、写 boundary 或产生正式 activation receipt。

拟定 session 仅 **2026-10-07**，runtime 为 `{RUNTIME}`，目标为 `{target}`；目标及 WAL/SHM/journal/preparing 事前事后均不存在。首次真实接受前必须重新核对实际 session、绝对路径、schema 与目标 absence；跨日须重新出声明并按新 canonical SHA 接受，继续会话不自动构成批准。独立 evidence 临时 import DB 不能冒充这个 runtime 的正式新期库。

实际 AST 提取的九个业务表/两个显式索引 SQL SHA 为 `{literal_sha}`；同已有 minute-schema.sql 字节一致。本次没有执行 SQL，没有 actual sqlite_master schema SHA。正式 initialize 还会添加 data_epoch_boundary 并写一条接受摘要，因此 SQL 文本 SHA 与建库后 sqlite_master schema SHA 是两种不同事实，应分别记录。

四个已有 preserved store 的 snapshot/active 具体路径、身份、bytes/mtime、选定整型 rowid 水位和 prior 实测 SHA 已在 JSON逐项绑定。当前 metadata 前后等于此前真实 preparation；本次没有重复重算八个大库全文件 SHA，也没有开 SQLite，不能把本次 metadata 检查说成新的全库字节/业务审计。原件没有访问；四 active、snapshot 和冻结分钟缓存没有写入。

可审阅历史范围固定 Sep09–Oct06、100 mapped/11 unknown，778771有效唯一分钟、1229缺口，未形成当日连续分钟或策略资格；旧持仓/事件/任务/评估 UNKNOWN，不重放过期机会。已有数据放缓存，不因继续工程自动接入生产库。

正式建库缺门：具体 O-SETUP/OWNER/NEW_MINUTE_EPOCH 的真实人工决定，精确绑定 declaration canonical SHA、runtime/minute路径、epoch_id/session、UNKNOWN及带时区 accepted_at；本工具不代写该记录。initialize 只允许新目标/无 companions/无 preparing、实际 schema text SHA一致、有界五秒初始化。创建后还需只读 actual schema/水位/边界事实，再由 activation producer观察四 COMPLETE_VERIFIED 与 minute NEW_EPOCH_VERIFIED；producer不创建/导入/批准。

当前 record_recovery_activation CLI 的 roots 只有工作区入口与 C:\\KQUANT-Recovery，会拒绝 sibling evidence 的材料/新运行根。不要通过 --test-only 或伪造 OWNER 绕过。独立工程 import 候选可由 ROOT 另用 AST SQL和只读原页闭包创建在全新 evidence 目录，明确 ACCEPTANCE_PENDING、不写已接受 boundary、不给 NEW_EPOCH_VERIFIED，保持四 active/cache不动；这不是正式新期激活材料。

生产仍另需当前整候选 O-LAUNCH/final_runtime_accepted 与路径绑定/连续性材料，以及真实时钟/当日输入/价格尺度/合约交付/3秒BBO资格。仅上述数据期决定不能放行生产、资格信号或真实交易。全机校时未授权。

实际 precheck JSON SHA：`{digest}`。下一安全动作是审阅这份具体范围；正式接受缺门仍保留，不把工程授权或 TEST_ONLY fixture冒充人工批准。
"""
    with (OUT / "NEW_MINUTE_EPOCH_SCOPE_REVIEW.md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(json.dumps({"status": value["status"], "precheck": str(OUT / "ACTUAL_NEW_EPOCH_PRECHECK.json"),
                      "sha256": digest, "review": str(OUT / "NEW_MINUTE_EPOCH_SCOPE_REVIEW.md"),
                      "database_opens": 0, "minute_created": False, "owner_acceptance_written": False, "can_launch": False}))


if __name__ == "__main__":
    main()
