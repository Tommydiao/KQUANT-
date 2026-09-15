"""Create new evidence receipts for implemented W0/data tasks; never overwrite runs."""
import argparse
from collections import Counter
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery, atomic_json, load, sha
from kquant_crypto.hybrid_quote_contract_v12 import describe_quote, CONTRACT


def run(out):
    out=(ROOT/out).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True,exist_ok=False)
    tests=['tests/test_hybrid_delivery.py','tests/test_hybrid_quote_contract_v12.py',
           'tests/test_hybrid_observation.py','tests/test_hybrid_clock.py',
           'tests/test_hybrid_labels.py','tests/test_hybrid_m2.py','tests/test_hybrid_partitions.py']
    start=time.monotonic()
    command=[sys.executable,'-m','pytest','-q',*tests]
    proc=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=240)
    (out/'tests.log').write_bytes(proc.stdout+proc.stderr)
    test_result={'command':command,'cwd':str(ROOT),'exit_code':proc.returncode,
                 'elapsed_seconds':time.monotonic()-start,'log_sha256':sha(out/'tests.log'),
                 'source_hashes':{p:sha(ROOT/p) for p in tests},
                 'implementation_hashes':{p:sha(ROOT/p) for p in (
                     'kquant_crypto/hybrid_delivery.py','kquant_crypto/hybrid_delivery_audit.py',
                     'kquant_crypto/hybrid_quote_contract_v12.py','scripts/run_hybrid_delivery.py')}}
    atomic_json(out/'tests_result.json',test_result)
    if proc.returncode: raise ValueError('Required evidence tests failed')
    old=ROOT/'outputs/hybrid_regime_v1/clock_segment_20260905_02'
    rows=[json.loads(line) for line in (old/'qualified_quotes.jsonl').read_text().splitlines()]
    described=[describe_quote(q) for q in rows]
    semantic={'contract':CONTRACT,'inspected':len(rows),'qualified_samples':sum(q['eligible_sample'] for q in described),
              'reasons':dict(Counter(reason for q in described for reason in q['reasons'])),
              'historical_projection_only':True,'old_quotes_modified':False,
              'strict_price_level_timestamp_claimed':False,'actual_exchange_fill_claimed':False,
              'time_denominator_slo':None,'slo_reason':'Old segment lacks predeclared absolute observation boundaries; not infer from message count',
              'inputs':{str(p.relative_to(ROOT)):sha(p) for p in (old/'qualified_quotes.jsonl',old/'report.json')}}
    atomic_json(out/'ticker_semantics.json',semantic)
    if semantic['qualified_samples'] != 322: raise ValueError('Quote semantic regression')
    schedule=Path.home()/'.codex/automations/kquant/automation.toml'
    (out/'schedule_snapshot.toml').write_bytes(schedule.read_bytes())
    # Names only; no credentials are read, logged, serialized or returned.
    inherited_secret_names=[k for k in os.environ if any(s in k.upper() for s in ('BINANCE_LIVE','PRODUCTION_SECRET','PRODUCTION_API_KEY'))]
    operations={'existing_schedule_id':'kquant','new_schedule_created':False,
                'user_authority':'Current explicit request to verify and reuse existing scheduling',
                'new_fees':0,'live_enabled':False,'actual_testnet_operations':False,
                'production_readonly_approved':False,'production_secrets_inherited_detected':bool(inherited_secret_names),
                'max_session_seconds':3600,'scheduler_snapshot_sha256':sha(out/'schedule_snapshot.toml'),
                'schedule_requires_codex_host_available':True,'no_claim_of_continuous_market_observation':True}
    atomic_json(out/'operations.json',operations)
    if inherited_secret_names: raise ValueError('Production credentials present in developer environment; do not continue scheduler acceptance')
    db=Delivery(ROOT)
    intake='outputs/hybrid_delivery/intake_20260906_01/audit.json'
    mapping={
      'T00':[intake,'outputs/hybrid_delivery/intake_20260906_01/processes.json'],
      'T01':[str((out/'tests_result.json').relative_to(ROOT)),str((out/'tests.log').relative_to(ROOT))],
      'T02':['docs/HYBRID_DELIVERY_A1_V1_2.md',intake,str((out/'operations.json').relative_to(ROOT))],
      'T03':[str((out/'operations.json').relative_to(ROOT)),str((out/'schedule_snapshot.toml').relative_to(ROOT)),str((out/'tests_result.json').relative_to(ROOT))],
      'T10':[str((out/'ticker_semantics.json').relative_to(ROOT)),str((out/'tests_result.json').relative_to(ROOT)),'docs/HYBRID_M2_DELIVERY_V1_1.md'],
      'T13':[intake,'outputs/hybrid_regime_v1/dev_fit_20260905_03/audit.json'],
      'T11':[str((out/'tests_result.json').relative_to(ROOT)),str((out/'tests.log').relative_to(ROOT)),'docs/HYBRID_M2_DELIVERY_V1_1.md'],
    }
    (out/'receipts').mkdir()
    try:
        for tid,refs in mapping.items():
            r={'task_id':tid,'board_sha256':sha(db.board_path),'status':'VERIFIED',
               'evidence':[{'path':p,'sha256':sha(ROOT/p)} for p in refs],
               'acceptance':{a:refs for a in db.tasks[tid]['acceptance']},
               'verified_at_raw_local_utc':datetime.now(UTC).isoformat(),
               'machine_evidence':intake if tid in ('T00','T13') else None,
               'scope':'Local engineering evidence only; no G2-G11 pass'}
            atomic_json(out/'receipts'/f'{tid}.json',r)
        result=db.run_ready(str((out/'receipts').relative_to(ROOT)),120)
        # Explicitly distinguish natural observation wait from an unfinished code task.
        for tid,reason,trigger in [
            ('T12','No 72-hour scheduled observation and no natural quote-aware matured label yet','New continuous observer with frozen SLO and a natural completed lifecycle'),
            ('T17','Zero matching QUOTE_AWARE mature training labels; A27 are legacy proxy','New audited matching-target mature labels')]:
            r={'task_id':tid,'board_sha256':sha(db.board_path),'status':'WAIT_DATA',
               'evidence':[{'path':mapping['T10'][0],'sha256':sha(ROOT/mapping['T10'][0])}],
               'owner':'data-runtime','reason':reason,'blocked_scope':[tid], 'next_trigger':trigger}
            p=out/'receipts'/f'{tid}.json'; atomic_json(p,r); db.record(str(p.relative_to(ROOT)))
        atomic_json(out/'dispatch_result.json',result)
        atomic_json(out/'status.json',db.status())
        return result
    finally: db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    print(json.dumps(run(args.output),ensure_ascii=False,indent=2))
