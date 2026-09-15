"""Audit economic grouping of existing holding targets without training."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_target_contract import holding_identity,interval_components


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New independent output required')
    source=ROOT/'outputs/hybrid_delivery/multifactor_policy_holding_v2_20260908_01'
    portfolio=ROOT/'outputs/hybrid_delivery/multifactor_portfolio_20260907_02'
    report=json.loads((source/'report.json').read_text());path=source/'holding_targets.jsonl'
    if sha(path)!=report['labels_hash'] or report['training_enabled']:raise ValueError('Frozen untrained labels required')
    inputs={str(path.relative_to(ROOT)):sha(path)};trades={}
    for name in ('ORIGINAL','FIXED_2_5R','FIXED_3R','T1','T2'):
        file=portfolio/(name+'_1')/'trades.jsonl';inputs[str(file.relative_to(ROOT))]=sha(file)
        for line in file.read_text().splitlines():
            trade=json.loads(line);trades[trade['trade_id']]=(trade,sha(file))
    groups=defaultdict(list);rows=[];seen=set()
    for line in path.read_text().splitlines():
        row=json.loads(line);trade,source_hash=trades[row['trade_id']]
        if row['source_trade_hash']!=source_hash:raise ValueError('Parent source hash mismatch')
        identity=holding_identity(row,trade)
        key=(identity['policy_id'],identity['parent_trade_id'],identity['snapshot_time'])
        if key in seen:raise ValueError('Duplicate holding state')
        seen.add(key);rows.append(identity);groups[tuple(identity['economic_key'])].append(identity)
    summaries=[]
    for key,items in sorted(groups.items()):
        start=min(r['information_start'] for r in items);end=max(r['information_end'] for r in items)
        summaries.append(dict(economic_key=key,rows=len(items),parent_trades=len({r['parent_trade_id'] for r in items}),
            policies=len({r['policy_id'] for r in items}),information_start=start,information_end=end,
            group_information_hours=(end-start)/3600,partition_assigned=False))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'holding_identity.jsonl').open('x',encoding='utf-8') as handle:
        for row in rows:handle.write(json.dumps(row)+'\n')
    result=dict(scope='DEV_ONLY',training_enabled=False,execution_enabled=False,rows=len(rows),
        policy_parent_trades=len({r['parent_trade_id'] for r in rows}),economic_opportunities=len(groups),
        max_group_information_hours=max(r['group_information_hours'] for r in summaries),groups=summaries,
        overlap_components=interval_components(summaries),
        identity_hash=sha(out/'holding_identity.jsonl'),inputs=inputs,
        inputs_unchanged=all(sha(ROOT/name)==value for name,value in inputs.items()),
        limitations=['Economic identity is not market independence','No new partition assigned; overlapping group intervals must be purged together','No holding target model trained or activated'])
    write_json(out/'report.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('groups','inputs','overlap_components')},default=str));print('overlap_components='+str(len(result['overlap_components'])))


if __name__=='__main__':main()
