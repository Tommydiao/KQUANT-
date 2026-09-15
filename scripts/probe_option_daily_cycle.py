"""Bounded real-market cycle in a NEW database; never starts or stops an existing service."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from kquant.options_radar_supervisor import OptionRadarSupervisor
from kquant.options_radar import latest_premarket_report, monitor_option_plans, option_research_report
from kquant.option_runtime import runtime_status
from kquant.realtime_instructions import AlertEventHub
from kquant.longbridge_provider import longbridge_runtime
from kquant.stock_store import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    load_dotenv(ROOT/'.env',override=False)
    db=args.output/'probe.sqlite3'
    service=OptionRadarSupervisor(db,AlertEventHub())
    started=datetime.now(UTC).isoformat()
    timer=time.monotonic()
    result={'evidence_type':'REAL_MARKET_ISOLATED_MANUAL_CYCLE', 'production_service_enabled':False,
            'started_at':started,'database':str(db.resolve()), 'notifications_dispatched':False}
    try:
        result['cycle']=service.cycle_once()
        result['monitor']=monitor_option_plans(db)
        result['report']=latest_premarket_report(db)
        result['research']=option_research_report(db)
        result['runtime']=runtime_status(db)
        with connect(db) as conn:
            result['counts']={table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                              for table in ('option_radar_runs','option_opportunities','option_plans','option_quote_evidence','option_outcomes')}
        result['status']='completed'
    except Exception as exc:
        result['status']='failed'
        result['error_type']=type(exc).__name__
        result['runtime']=runtime_status(db)
    finally:
        result['finished_at']=datetime.now(UTC).isoformat()
        result['elapsed_seconds']=time.monotonic()-timer
        (args.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        print(json.dumps({key:value for key,value in result.items() if key not in ('report','research')},indent=2,ensure_ascii=False,default=str))
        longbridge_runtime()._reset()
        longbridge_runtime()._executor.shutdown(wait=False,cancel_futures=True)
    if result['status']!='completed':
        raise SystemExit(1)

if __name__=='__main__':
    main()
