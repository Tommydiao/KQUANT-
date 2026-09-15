"""Audit existing exposed holding-group intervals against original DEV boundaries."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.candidate_policy import digest
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_group_interval_audit import audit_group_partitions


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve();base=ROOT/'outputs/hybrid_delivery'
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    source=base/'rx03_holding_identity_20260909_02'
    report=json.loads((source/'report.json').read_text())
    if sha(source/'holding_identity.jsonl')!=report['identity_hash']:raise ValueError('Identity changed')
    path=ROOT/'outputs/hybrid_regime_v1/m2_development_20260905_04/partition_policy.json'
    policy=json.loads(path.read_text())
    if digest({k:v for k,v in policy.items() if k!='policy_hash'})!=policy['policy_hash']:
        raise ValueError('Original DEV boundaries changed')
    identities=[json.loads(s) for s in (source/'holding_identity.jsonl').read_text().splitlines()]
    groups=[]
    for g in report['groups']:
        members=[r for r in identities if r['economic_key']==g['economic_key']]
        if (len(members)!=g['rows'] or min(r['information_start'] for r in members)!=g['information_start']
            or max(r['information_end'] for r in members)!=g['information_end']):
            raise ValueError('Group interval does not match label identities')
        groups.append(g)
    result=audit_group_partitions(groups,policy['boundaries'])
    result.update(identity_hash=report['identity_hash'],source_report_hash=sha(source/'report.json'),
        original_partition_hash=policy['policy_hash'],original_embargo_seconds=policy['embargo_seconds'],
        groups=len(groups),holding_rows=len(identities),
        max_group_hours=max((g['information_end']-g['information_start'])/3600 for g in groups),
        counts=dict(Counter((r['proposed_partition'] or 'outside')+':'+(r['interval_exclusion'] or 'INTERVAL_ONLY_PASS') for r in result['rows'])),
        code_hash=sha(Path(__file__)),helper_hash=sha(ROOT/'kquant_crypto/hybrid_group_interval_audit.py'),
        old_labels_or_partitions_modified=False)
    out.mkdir(exist_ok=False);write_json(out/'report.json',result)
    print(json.dumps({k:result[k] for k in ('groups','holding_rows','max_group_hours','counts','training_enabled')}))


if __name__=='__main__':main()
