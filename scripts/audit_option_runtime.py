"""Read-only provider capability samples; no strategy, migrations, subscriptions or orders."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from kquant.longbridge_provider import longbridge_runtime
from kquant.options_expression import option_contract_snapshot, option_market_status, _attr, _timestamp
from kquant.stock_signals import _parse_longbridge_time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--contract', required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    load_dotenv(ROOT/'.env', override=False)
    runtime = longbridge_runtime()
    samples = []
    for _ in range(3):
        start, timer = datetime.now(UTC), time.monotonic()
        try:
            quote = list(runtime.pull_quote('SPY.US', 10))[0]
            received = datetime.now(UTC)
            raw = _attr(quote, 'timestamp')
            normalized = _parse_longbridge_time(raw)
            sources = {'regular_trade': _timestamp(_attr(quote, 'timestamp'))}
            for name in ('pre_market_quote', 'post_market_quote', 'overnight_quote'):
                sources[name] = _timestamp(_attr(_attr(quote, name), 'timestamp'))
            samples.append(dict(request_started_at=start.isoformat(), received_at=received.isoformat(),
                elapsed_seconds=time.monotonic()-timer, source_trade_times=sources,
                raw_trade_time=repr(raw), raw_trade_time_type=type(raw).__name__,
                raw_tzinfo=str(getattr(raw, 'tzinfo', None)),
                stock_parser_trade_time=normalized.isoformat() if normalized else None,
                stock_parser_event_minus_receipt_seconds=(normalized-received).total_seconds() if normalized else None,
                event_minus_receipt_seconds={key:(datetime.fromisoformat(value.replace('Z','+00:00'))-received).total_seconds()
                    for key,value in sources.items() if value},
                source='Longbridge QuoteContext.quote', local_time_is_not_source_time=True))
        except Exception as exc:
            samples.append(dict(request_started_at=start.isoformat(), received_at=datetime.now(UTC).isoformat(),
                                elapsed_seconds=time.monotonic()-timer, error_type=type(exc).__name__))
        time.sleep(1)
    market = option_market_status()
    contract = option_contract_snapshot(args.contract)
    # Do not include arbitrary provider error strings or credential-bearing environment values.
    contract.pop('provider_errors', None)
    payload = dict(generated_at=datetime.now(UTC).isoformat(), interpreter=sys.executable,
        sdk_version=version('longbridge'), git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        clock_samples=samples, provider={key:market.get(key) for key in ('status','provider','opra_status','quote_packages')},
        contract=contract, strict_event_time_verified=False, production_database_written=False,
        calendar_sdk_methods=[name for name in dir(type(runtime.context())) if any(word in name.lower() for word in ('calendar','earn','dividend'))])
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    (args.output/'audit.json').write_text(data,encoding='utf-8')
    (args.output/'audit.sha256').write_text(hashlib.sha256(data.encode()).hexdigest(),encoding='ascii')
    print(data)
    runtime._reset()
    runtime._executor.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
