"""Bounded TEST_ONLY preparation profile; fresh temporary stores, no API calls."""
import argparse
import cProfile
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import pstats
import sys
from copy import deepcopy
import importlib.abc
import importlib.util
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent/'opening-first-hour'
if '--baseline-handoff' in sys.argv:
    baseline = Path(r'E:\kquant 1007\KQUANT-GitHub-Handoff-20261031\recovery\20261031\source\development\strategy-usability-v1\delivery-7d\opening-first-hour')
    class BaselineFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in {'prepared_generation','method_snapshot','first_hour_minute_decisions'}:
                return importlib.util.spec_from_file_location(fullname,baseline/(fullname+'.py'))
    sys.meta_path.insert(0, BaselineFinder())
os.environ['KQUANT_TEST_WEEKEND_OVERLAY'] = str(HERE)
os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = str(HERE.parent/'monday-signal-llm/release/local-candidate-7896a20b9c18c711/deployment-projection.json')
sys.path.insert(0, str(FIRST/'assembly'))
from bootstrap import activate
activate()
from test_generation_handoff import actual_lane, prepare, validate
from first_hour_minute_decisions import LOCAL_METHOD
from kquant import options_one_minute as common
import first_hour


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--baseline-handoff', action='store_true')
    parser.add_argument('--full-sources', action='store_true')
    parser.add_argument('--last-checkpoint-only', action='store_true')
    args = parser.parse_args()
    if not args.name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('INVALID_EVIDENCE_NAME')
    out = HERE/'evidence'/args.name
    out.mkdir(exist_ok=False)
    report = {'test_only':True,'api_calls':0,'business_store_access':False,'cases':[]}
    with TemporaryDirectory(prefix='KQUANT_TEST_ONLY_generation_') as temp:
        with actual_lane(Path(temp)) as (lane, _, now, key, job, bars, reviews):
            opening, _ = first_hour.session_bounds_utc(job[1])
            now[0] = opening+timedelta(minutes=55, seconds=1)
            raw = json.dumps({'approved_by':'OWNER','status':'APPROVED','test_only':True,
                'method_hash':common.digest(LOCAL_METHOD),'approved_at':opening.isoformat(),
                'valid_until':(now[0]+timedelta(hours=1)).isoformat()}).encode()
            (Path(temp)/'TEST_ONLY-receipt.json').write_bytes(raw)
            proof = {'semantics':'CLOSED_SNAPSHOT_ADOPTION','status':'ACCEPTED',
                'method':LOCAL_METHOD,'acceptance_path':'TEST_ONLY-receipt.json',
                'acceptance_sha256':sha256(raw).hexdigest()}
            source_reviews = {'canonical_resolution_method':proof}
            symbols = ['TEST'+str(i) for i in range(7)]
            if args.full_sources:
                fixture = HERE.parents[4]/'source/evidence/new-machine-20261008/sunday-metadata-short2-20261101'
                if not json.loads((fixture/'TEST_ONLY.json').read_text()).get('test_only'):
                    raise ValueError('TEST_ONLY_SOURCE_FIXTURE_REQUIRED')
                source_reviews = json.loads((fixture/'TEST_ONLY-sources.json').read_text())
                source_reviews['canonical_resolution_method'] = proof
                (Path(temp)/'test-fact.txt').write_bytes((fixture/'test-fact.txt').read_bytes())
                symbols = [name for name in source_reviews['instrument_price_actions'] if name != job[0]][:7]
            reviews.write_text(json.dumps(source_reviews),encoding='utf-8')
            rows = []
            for i in range(55):
                start = opening+timedelta(minutes=i)
                received = start+timedelta(minutes=1,milliseconds=2)
                bar = {**(bars[i] if i < len(bars) else bars[0]),'open_at':start.isoformat(),
                    'available_at':(start+timedelta(minutes=1)).isoformat(),
                    'received_at':received.isoformat(),
                    'sdk_evidence':{'provider_symbol':'AI.US','adjustment':'NoAdjust',
                        'interface':'QuoteContext.candlesticks',
                        'request_started_at':received.isoformat(),
                        'clock_evidence':{'state':'VERIFIED_BOUND','uncertainty_ms':1,
                            'source_hash':'TEST_ONLY_CLOCK','checked_at':start.isoformat()}}}
                common.save_bar(bar, job[1].isoformat(), lane.minute_path)
                rows.append(bar)
            job = (*job[:2], rows, *job[3:])
            def reference(symbol):
                native = dict(symbol=symbol,provider_symbol=symbol+'.US',currency='USD',
                    source='LONGBRIDGE_SECURITY_STATIC_INFO',received_at=now[0].isoformat())
                native['source_hash'] = common.digest(native)
                return {'raw_quote':dict(symbol=symbol,provider_status='available',previous_close=99,
                    currency='USD',currency_evidence=native,requested_at=now[0].isoformat(),
                    received_at=now[0].isoformat(),quote_time=now[0].isoformat(),test_only=True)}
            if args.full_sources:
                job = (*job[:4], reference(job[0]))
            key = (*key[:3], 11)
            entries = [(key,job)]
            for symbol in symbols:
                native = deepcopy(rows)
                for row in native:
                    row['symbol'] = symbol
                    row['sdk_evidence']['provider_symbol'] = symbol+'.US'
                    common.save_bar(row,job[1].isoformat(),lane.minute_path)
                entries.append(((key[0],key[1],symbol,11),(symbol,job[1],native,job[3],
                    reference(symbol) if args.full_sources else job[4])))
            def prepare_batch():
                reviews_value, pair = lane._source_reviews(),first_hour.policies()
                with lane._input_batch(entries=entries):
                    return [lane._prepare_generation(k,j,0,reviews_value,pair) for k,j in entries]
            operations = [('prepare',lambda:prepare(lane,key,job)),
                                     ('validate',lambda:validate(lane,generation)),
                                     ('batch_prepare',prepare_batch)]
            if args.last_checkpoint_only:
                final_now = now[0]
                now[0] -= timedelta(minutes=5)
                prior_entries = [((*k[:3], 10), j) for k,j in entries]
                reviews_value, pair = lane._source_reviews(), first_hour.policies()
                with lane._input_batch(entries=prior_entries):
                    for k,j in prior_entries:
                        lane._prepare_generation(k,j,0,reviews_value,pair)
                now[0] = final_now
                operations = [('batch_prepare',prepare_batch)]
            for name, operation in operations:
                profiler = cProfile.Profile()
                timings = []
                for _ in range(1 if args.last_checkpoint_only else 10):
                    started = perf_counter()
                    profiler.enable()
                    result = operation()
                    profiler.disable()
                    timings.append(perf_counter()-started)
                    if name == 'prepare':
                        generation = result
                    elif args.last_checkpoint_only:
                        generation = result[0]
                stream = io.StringIO()
                pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(50)
                (out/(name+'.txt')).write_text(stream.getvalue(),encoding='utf-8')
                report['cases'].append({'name':name,'seconds':timings,
                    'sum':sum(timings),'mean':sum(timings)/len(timings)})
            report['source_files'] = len(generation.files)
            report['minute_count'] = len(generation.job[2])
            report['decision_count'] = len(generation.decisions)
            report['incomplete_minutes'] = list(generation.minute_inputs[1])
            report['baseline_handoff'] = args.baseline_handoff
            report['full_sources'] = args.full_sources
            report['last_checkpoint_only'] = args.last_checkpoint_only
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
