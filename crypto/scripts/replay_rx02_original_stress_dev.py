"""Fill the missing original-policy stress scenario, never alter frozen runs."""
import argparse
import ast
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from replay_multifactor_portfolio import run
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    base=ROOT/'outputs/hybrid_delivery';out=(ROOT/a.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New output required')
    reference=base/'multifactor_portfolio_20260907_02'
    prereg=json.loads((reference/'preregistration.json').read_text())
    original=json.loads((reference/'ORIGINAL_1/report.json').read_text())
    rules_path=ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    policy=load_policy(candidate='A')
    if policy!=prereg['policy'] or sha(rules_path)!=prereg['rules_hash']:
        raise ValueError('Frozen policy/rules mismatch')
    if sha(ROOT/'config/hybrid_exit_research_v1.json')!=prereg['exit_policy_hash']:
        raise ValueError('Exit contract changed')
    portable=base/'multifactor_portfolio_capsule_20260909_01'
    portable_contract=json.loads((portable/'preregistration.json').read_text())
    if portable_contract['reference_report_hash']!=sha(reference/'report.json'):
        raise ValueError('Portable replay reference mismatch')
    for name in ('trades.jsonl','equity.jsonl'):
        if sha(portable/'ORIGINAL_1'/name)!=sha(reference/'ORIGINAL_1'/name):
            raise ValueError('Portable BASE parity not established')
    for name,digest in portable_contract['source_hashes'].items():
        if name!='scripts/replay_multifactor_portfolio.py' and sha(ROOT/name)!=digest:
            raise ValueError('Frozen implementation changed: '+name)
    archive=base/'multifactor_portfolio_portable_20260909_02/authorized_dev_portfolio_replay.zip'
    with zipfile.ZipFile(archive) as z:
        archived_source=z.read('scripts/replay_multifactor_portfolio.py').decode('utf-8-sig')
    current_source=(ROOT/'scripts/replay_multifactor_portfolio.py').read_text(encoding='utf-8-sig')
    if ast.dump(ast.parse(archived_source))!=ast.dump(ast.parse(current_source)):
        raise ValueError('Portable runner semantic source mismatch')
    rules=json.loads(rules_path.read_text())['rules']
    capsule=base/'multifactor_dataset_capsule_20260909_01'
    data=load_capsule(capsule)
    if data.content_hash!=json.loads((reference/'report.json').read_text())['dataset_hash']:
        raise ValueError('Dataset changed')
    source_hashes={str(path.relative_to(ROOT)):sha(path) for path in
        (reference/'report.json',reference/'ORIGINAL_1/trades.jsonl',reference/'ORIGINAL_1/equity.jsonl')}
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json',dict(scope='EXPOSED_DEV_MISSING_COST_SCENARIO',
        policy=policy,cost_multipliers=[1,2],new_hypothesis=False,winner_selection=False,
        execution_enabled=False,dataset_hash=data.content_hash,source_hashes=source_hashes,
        code_hash=sha(Path(__file__)),original_preregistration_hash=sha(reference/'preregistration.json'),
        portable_contract_hash=sha(portable/'preregistration.json'),
        archive_hash=sha(archive),runner_hash=sha(ROOT/'scripts/replay_multifactor_portfolio.py'),
        runner_archive_ast_parity=True,
        source_contract='Verified portable implementation with original trade/equity byte parity',
        risk_note='Complete portfolio rerun re-applies sizing/risk at stressed costs; not fixed-fill BASE-R repricing.'))
    timeline={};hours={}
    for symbol,frames in data.bars.items():
        for bar in frames['5m']:timeline.setdefault(bar.start,{})[symbol]=bar
        for bar in frames['1h']:hours.setdefault(bar.start+3600,{})[symbol]=bar
    results={}
    for cost in (1,2):
        folder=out/f'ORIGINAL_{cost}';folder.mkdir()
        portfolio=ResearchPortfolio(policy,rules,exit_candidate='ORIGINAL',cost_multiplier=cost)
        _,_,result=run(portfolio,timeline,hours,data.manifest['window']['start'],data.cutoff,folder)
        if cost==1 and any(result[k]!=original[k] for k in ('trade_hash','equity_hash')):
            raise ValueError('BASE parity failed; stress not permitted')
        results[str(cost)]=result
        print(json.dumps(dict(cost=cost,trades=result['trades'],net_pnl=result['net_pnl'],profit_factor=result['profit_factor'])),flush=True)
    if any(sha(ROOT/name)!=digest for name,digest in source_hashes.items()):
        raise ValueError('Reference changed during replay')
    write_json(out/'report.json',dict(scope='EXPOSED_DEV_COST_STRESS',base_parity=True,
        scenarios=results,source_hashes=source_hashes,execution_enabled=False,independent_oos=False))


if __name__=='__main__':main()
