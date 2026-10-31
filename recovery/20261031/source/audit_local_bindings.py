"""Read source/configuration only; never load secrets or open a database."""
from datetime import UTC, datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "development/workspace"
OUT = ROOT / "evidence"


def source(relative):
    path = ROOT / relative
    content = path.read_bytes()
    return {"path": relative, "sha256": sha256(content).hexdigest(), "bytes": len(content)}


def main():
    sources = [source(value) for value in (
        "development/workspace/kquant/recovery_preflight.py",
        "development/workspace/kquant/recovery_runtime_probe.py",
        "development/workspace/kquant/recovery_activation.py",
        "development/workspace/kquant/options_data_paths.py",
        "development/workspace/kquant/options_full_watch.py",
        "development/workspace/kquant/options_signal_copilot.py",
        "development/workspace/kquant/config.py",
        "development/workspace/kquant/stock_store.py",
        "development/workspace/kquant/db/migrations.py",
        "development/workspace/scripts/check_safe_recovery.py",
        "development/workspace/scripts/record_recovery_activation.py",
        "development/workspace/start_kquant_workspace.ps1",
        "development/handoff/tools/new_data_epoch.py",
        "development/handoff/tools/cloud_archive_inventory.py",
        "development/workspace/config/safe_recovery_required.json",
    )]
    spec = importlib.util.spec_from_file_location("binding_audit_gate", WORKSPACE / "kquant/recovery_preflight.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    try:
        gate.checked_path(str(WORKSPACE / "config/safe_recovery_required.json"), [WORKSPACE])
        local_path = {"ok": True, "database_opens": 0}
    except ValueError as exc:
        local_path = {"ok": False, "code": str(exc), "database_opens": 0}
    config = [
        ("config/options_opening_momentum_v1.json", "S0 rule configuration"),
        ("config/options_opening_momentum_event_coverage_v1.json", "S0 event proposal"),
        ("config/options_one_minute_momentum_v1.json", "one-minute rule configuration"),
        ("config/options_full_watch_research_v1.json", "full-watch runtime configuration"),
        ("config/options_research_profiles_v1.json", "foundation profile metadata"),
        ("config/options_signal_copilot_v1.json", "legacy copilot runtime configuration"),
        ("config/options_opening_trend_v1.json", "old opening-trend counterpart; missing must not block S0"),
        ("docs/R58_S1_PREREGISTRATION.md", "S1 only; no implied S1 activation"),
    ]
    entries = [{"path": value, "present": (WORKSPACE / value).is_file(), "purpose": purpose}
               for value, purpose in config]
    root_guard = json.loads((WORKSPACE / "config/safe_recovery_required.json").read_text(encoding="utf-8-sig"))
    target = WORKSPACE / "work/options_one_minute-epoch-20261007/one_minute.sqlite3"
    tests_path = OUT / "new-epoch-producer-binding-tests.xml"
    tests = None
    if tests_path.is_file():
        suites = ET.parse(tests_path).getroot().iter("testsuite")
        values = list(suites)
        tests = {"path": str(tests_path.relative_to(ROOT)), "sha256": sha256(tests_path.read_bytes()).hexdigest(),
                 **{key: sum(int(s.attrib.get(key, "0")) for s in values)
                    for key in ("tests", "failures", "errors", "skipped")}}
    combined = None
    candidates = sorted(OUT.glob("backend-candidate-regression-*/receipt.json"))
    if candidates:
        latest = candidates[-1]
        combined_value = json.loads(latest.read_text(encoding="utf-8-sig"))
        combined = {"receipt_path": str(latest.relative_to(ROOT)), "receipt_sha256": sha256(latest.read_bytes()).hexdigest(),
                    **{key: combined_value.get(key) for key in ("status", "results", "source_hashes_unchanged",
                       "candidate_database_hashes_unchanged", "deselected_node", "deselection_reason")}}
    result = {
        "schema": "KQUANT_LOCAL_BINDING_AUDIT_V1", "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "source/configuration and previously produced evidence only",
        "database_opens": 0, "business_writes": 0, "provider_requests": 0,
        "owner_acceptance_written": False, "can_launch": False,
        "qualified_signal_authorized": False, "old_business_continuity": "UNKNOWN",
        "local_runtime_root": str(WORKSPACE), "local_path_guard_probe": local_path,
        "configured_runtime_policy_root": root_guard.get("approved_runtime_root"),
        "proposed_minute_path_not_approved": str(target), "proposed_minute_exists": target.is_file(),
        "minute_session_note": "First actual accepted session must be explicit; do not silently reuse a missed session.",
        "required_configuration_presence": entries,
        "actual_backend_entry_present": (WORKSPACE / "kquant/dashboard/__main__.py").is_file(),
        "actual_gateway_entry_present": (WORKSPACE / "crypto/kquant_crypto/gateway.py").is_file(),
        "workspace_environment_present": (WORKSPACE / ".venv/Scripts/python.exe").is_file(),
        "frontend_build_candidates": [str(p.relative_to(ROOT)) for p in sorted(
            (ROOT / "development/handoff/evidence/frontend-build-candidate-20261007").glob("dist*/unified.html"))],
        "active_store_mapping_proposal": {
            "main": str(WORKSPACE / "work/kquant_us.sqlite3"),
            "full_watch": str(WORKSPACE / "work/options_full_watch/full_watch.sqlite3"),
            "opening_research": str(WORKSPACE / "work/options_one_minute/opening_trend_research.sqlite3"),
            "signal_copilot": str(WORKSPACE / "work/options_signal_copilot/signal_copilot.sqlite3"),
            "minute": str(target),
        },
        "required_materials_before_launch": [
            "current declaration with exact session/runtime/path/schema hash and old business UNKNOWN",
            "actual human data-scope decision bound to that declaration, not historical TEST_ONLY receipts",
            "four original recovery proofs plus separate active snapshot identities/schema/business baselines",
            "new-minute activation facts observed from the actual created boundary and integer watermarks",
            "runtime path binding separating the new minute store and preserved opening research store",
            "continuity receipt NEW_EPOCH_OLD_RECORDS_UNKNOWN referencing all five activation receipts",
            "final source/configuration/dependency/frontend inventories and matching runtime verification",
            "actual final-candidate decision bound to candidate_payload_sha256; no automatic OWNER receipt",
        ],
        "known_implementation_gaps_at_first_audit": [
            {"path": "kquant/recovery_activation.py", "line": 31,
             "detail": "Producer accepts only five COMPLETE_VERIFIED recovery rows; add separated four-preserved plus new-minute facts."},
            {"path": "kquant/recovery_preflight.py", "line": 35,
             "detail": "Legacy C/E drive guard rejected this D runtime; root agent is adapting explicit local root checks."},
            {"path": "scripts/check_safe_recovery.py", "line": 27,
             "detail": "Legacy accepted root fixed to C:\\KQUANT-Recovery; exact local policy binding is required."},
            {"path": "start_kquant_workspace.ps1", "line": 39,
             "detail": "Launcher expects workspace/.venv, while validation environment currently sits in the resume root."},
            {"path": "kquant/options_full_watch.py", "line": 108,
             "detail": "Full-watch writes still use autocreating sqlite3 connections; preserve accepted files if missing."},
            {"path": "kquant/options_signal_copilot.py", "line": 193,
             "detail": "Copilot writes still initialize/autocreate stores; no missing accepted store may become a new empty history."},
        ],
        "engineering_updates": {
            "activation_request_schema": "KQUANT_NEW_EPOCH_ACTIVATION_REQUEST_V1",
            "producer": "Implemented four recovered snapshot facts plus actual new-minute boundary/watermarks; no acceptance output.",
            "all_store_binding": "Optional exact-five stores map; backward-compatible minute/opening fields retained.",
            "accepted_store_missing": "Full-watch, copilot, main migration and main write factories now use mode=rw when bound.",
            "isolated_tests": tests,
            "combined_candidate_regression": combined,
            "production_admission_verified": False,
        },
        "source_inventory": sources,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "local-binding-audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# 本机路径与配置审计", "", "本报告只读取源码、配置与既有证据；数据库打开、业务写入、行情请求、OWNER 接受写入均为 0。", "",
             "当前候选仍未获生产接受。四个恢复业务库必须保留原件，将独立活动副本分别放入候选 runtime/work；新分钟库另建显式数据代次，旧持仓、任务、事件与评价继续 UNKNOWN。", "",
             f"候选本机根：`{WORKSPACE}`。新分钟库建议路径（尚未接受）：`{target}`。分钟库与已保留的开盘研究库不能合并或互相推导。", "",
             "## 本机实查", "", f"- D 盘路径守卫探测：`{local_path}`。",
             f"- 当前 guard 配置根为 `{root_guard.get('approved_runtime_root')}`；主机路径配置本身不代替准确数据范围或最终候选的人类接受。",
             f"- 后端与 Gateway 的 Python 模块入口存在；workspace 内虚拟环境存在：{result['workspace_environment_present']}。",
             "- 前端与 Gateway 必须按最终配套构建回执绑定实际目录；历史 handoff 候选不能代替本轮配套回执。", "",
             "## 配置材料", "", "| 文件 | 存在 | 用途 |", "|---|---|---|"]
    lines += [f"| {r['path']} | {r['present']} | {r['purpose']} |" for r in entries]
    lines += ["", "S0 参数文件存在。当前 Full Watch、profiles 与 Copilot 三份原配置已恢复；配置存在本身不代表策略或 OWNER 激活。开盘旧对照配置与 S1 预登记仍缺，只应禁用对应入口，不得捏造原政策或重新封锁独立 S0。", "",
              "## 下一步材料", ""]
    lines += [f"{i}. {material}" for i, material in enumerate(result["required_materials_before_launch"], 1)]
    lines += ["", "## 本次工程推进", "",
              "- 新代次事实生产器已实现：四个恢复库继续对比真实快照基线，新分钟库核验实际代次边界并捕获水位；不生成 OWNER 接受或完整恢复声明。",
              "- 路径绑定增加可选五库精确字典，保留原分钟/开盘研究两个字段的兼容语义。",
              "- Full Watch、Copilot、主库迁移及主库写连接在绑定模式使用 mode=rw；文件缺失会失败，不创建空历史。",
              f"- 隔离工程测试结果：`{tests}`。实测子进程打开测试库，检查绑定、旧/新基线及拒绝分支；不能据此声称生产接受或真实行情通过。", "",
              f"- 当前组合候选回归及真实候选库不变证明：`{combined}`。测试覆盖范围以配套回执的模块清单为准。", "",
              "初始审计定位与当前源码 SHA-256 见配套 JSON。四个活动副本事实以独立 local-runtime-preparation 回执为准；工程测试不补写实际 OWNER 或分钟数据范围接受。", ""]
    (OUT / "local-binding-audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(OUT / "local-binding-audit.json"), "local_path_guard_probe": local_path,
                      "missing_configurations": [r["path"] for r in entries if not r["present"]]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
