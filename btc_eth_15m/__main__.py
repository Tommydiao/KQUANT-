from __future__ import annotations

import argparse
import json

from btc_eth_15m.agent_harness.cli import add_agent_parser, run_agent_command


class _Console:
    def print(self, value) -> None:
        print(value)


console = _Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btc-eth-15m")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config/default.yml", help="Path to config YAML.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_agent_parser(subparsers)
    subparsers.add_parser("fetch", parents=[common], help="Fetch Binance USD-M Futures klines.")
    subparsers.add_parser("backtest", parents=[common], help="Run backtest and write reports.")
    sweep = subparsers.add_parser("sweep", parents=[common], help="Run a small parameter sweep.")
    sweep.add_argument("--variant", action="append", default=None, help="Run only the named sweep variant. Can be repeated.")
    stdlib_sweep = subparsers.add_parser(
        "stdlib-sweep",
        parents=[common],
        help="Run the fixed ETH short sweep with a pure-stdlib trend-pullback backtester.",
    )
    stdlib_sweep.add_argument("--variant", action="append", default=None, help="Run only the named stdlib sweep variant. Can be repeated.")
    paper = subparsers.add_parser("paper", parents=[common], help="Emit paper-trading signal snapshot.")
    paper.add_argument("--once", action="store_true", help="Run one snapshot and exit.")
    report = subparsers.add_parser("report", parents=[common], help="Regenerate report for a run id.")
    report.add_argument("--run-id", required=True)
    v2_report = subparsers.add_parser("v2-report", parents=[common], help="Generate v2 research report from a sweep CSV.")
    v2_report.add_argument("--sweep-csv", default=None)
    replay_sweep = subparsers.add_parser(
        "replay-sweep",
        parents=[common],
        help="Filter an existing trade replay without placing orders or running pandas backtests.",
    )
    replay_sweep.add_argument("--run-id", required=True)
    meta = subparsers.add_parser("meta-filter", parents=[common], help="Analyze walk-forward meta-filter rules for a run.")
    meta.add_argument("--run-id", required=True)
    dashboard = subparsers.add_parser("dashboard", parents=[common], help="Run the local Web trading console.")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    subparsers.add_parser("readiness-report", parents=[common], help="Write a live-readiness report without placing orders.")
    exchange_self_check = subparsers.add_parser(
        "exchange-self-check",
        parents=[common],
        help="Run Paper/Testnet/Live broker self-check without placing live orders.",
    )
    exchange_self_check.add_argument("--mode", choices=["paper", "testnet", "live"], default="testnet")
    exchange_sync = subparsers.add_parser(
        "exchange-sync",
        parents=[common],
        help="Fetch a read-only Paper/Testnet/Live account/order/position sync snapshot.",
    )
    exchange_sync.add_argument("--mode", choices=["paper", "testnet", "live"], default="testnet")
    refresh_market = subparsers.add_parser("refresh-market", parents=[common], help="Fetch recent public market data only.")
    refresh_market.add_argument("--lookback-bars", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "agent":
        return run_agent_command(args)

    from btc_eth_15m.config import load_config

    config = load_config(args.config)

    if args.command == "fetch":
        from btc_eth_15m.data import fetch_all

        results = fetch_all(config)
        for result in results:
            console.print(
                f"{result.symbol}: inserted {result.rows} rows"
                f" ({result.start_time or 'no new rows'} -> {result.end_time or 'no new rows'})"
            )
        return 0

    if args.command == "backtest":
        from btc_eth_15m.backtest import run_backtest
        from btc_eth_15m.reporting import write_report

        result = run_backtest(config)
        report_path = write_report(config, result["run_id"])
        console.print(json.dumps(result["summary"], indent=2))
        console.print(f"Report: {report_path}")
        return 0

    if args.command == "sweep":
        from btc_eth_15m.sweep import run_sweep

        out_path = run_sweep(config, variant_names=args.variant)
        console.print(f"Sweep report: {out_path}")
        return 0

    if args.command == "stdlib-sweep":
        from btc_eth_15m.stdlib_sweep import run_stdlib_eth_short_sweep

        out_path = run_stdlib_eth_short_sweep(config, variant_names=args.variant)
        console.print(f"Stdlib sweep report: {out_path}")
        return 0

    if args.command == "paper":
        from btc_eth_15m.paper import run_paper_once

        if not args.once:
            console.print("--once is required in v1.")
            return 2
        out_path = run_paper_once(config)
        console.print(f"Paper signal: {out_path}")
        return 0

    if args.command == "report":
        from btc_eth_15m.reporting import write_report

        report_path = write_report(config, args.run_id)
        console.print(f"Report: {report_path}")
        return 0

    if args.command == "v2-report":
        from btc_eth_15m.research import write_v2_report

        report_path = write_v2_report(config, args.sweep_csv)
        console.print(f"V2 research report: {report_path}")
        return 0

    if args.command == "replay-sweep":
        from btc_eth_15m.replay_sweep import write_replay_filter_sweep

        report_path = write_replay_filter_sweep(config, args.run_id)
        console.print(f"Replay-filter sweep report: {report_path}")
        return 0

    if args.command == "meta-filter":
        from btc_eth_15m.meta import write_meta_filter_report

        report_path = write_meta_filter_report(config, args.run_id)
        console.print(f"Meta-filter report: {report_path}")
        return 0

    if args.command == "dashboard":
        import uvicorn

        from btc_eth_15m.dashboard.app import create_app

        app = create_app(args.config)
        console.print(f"Dashboard: http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "readiness-report":
        from btc_eth_15m.dashboard.app import live_readiness, write_readiness_report

        payload = live_readiness(config)
        report_path = write_readiness_report(config, payload)
        console.print(json.dumps(payload, indent=2))
        console.print(f"Live readiness report: {report_path}")
        return 0

    if args.command == "exchange-self-check":
        from btc_eth_15m.dashboard.broker import broker_for_mode
        from btc_eth_15m.dashboard.state import (
            latest_exchange_self_check_summary,
            record_event,
            record_exchange_self_check,
        )

        payload = broker_for_mode(config, args.mode).self_check()
        record_exchange_self_check(config.db_path, payload)
        summary = latest_exchange_self_check_summary(
            config.db_path,
            args.mode,
            max_age_seconds=config.exchange_self_check_max_age_seconds,
        )
        record_event(
            config.db_path,
            "self-check",
            f"Exchange self-check: {args.mode}",
            summary or {"mode": args.mode, "passed": payload.get("passed")},
        )
        payload["last_self_check"] = summary
        console.print(json.dumps(payload, indent=2))
        return 0 if payload.get("passed") else 1

    if args.command == "exchange-sync":
        from btc_eth_15m.dashboard.broker import broker_for_mode
        from btc_eth_15m.dashboard.state import latest_exchange_sync_summary, record_event, record_exchange_sync

        payload = broker_for_mode(config, args.mode).sync_snapshot()
        record_exchange_sync(config.db_path, payload)
        summary = latest_exchange_sync_summary(
            config.db_path,
            args.mode,
            max_age_seconds=config.exchange_sync_max_age_seconds,
        )
        record_event(
            config.db_path,
            "sync",
            f"Exchange sync snapshot: {args.mode}",
            summary or {"mode": args.mode, "passed": payload.get("passed")},
        )
        payload["last_sync"] = summary
        console.print(json.dumps(payload, indent=2))
        return 0 if payload.get("passed") else 1

    if args.command == "refresh-market":
        from dataclasses import asdict

        from btc_eth_15m.data import fetch_recent_all, market_freshness

        results = fetch_recent_all(config, lookback_bars=args.lookback_bars)
        payload = {
            "results": [asdict(result) for result in results],
            "market_freshness": market_freshness(config),
        }
        console.print(json.dumps(payload, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
