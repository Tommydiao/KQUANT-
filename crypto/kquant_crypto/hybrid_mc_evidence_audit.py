"""Revalidate fixed MC engineering artifacts; never grants numerical admission."""
from pathlib import Path
from .hybrid_delivery import load, sha


def audit_mc_engineering(root):
    root=Path(root).resolve()
    base=root/'outputs/hybrid_delivery'
    run=base/'mc_process_load_20260906_03'
    prereg=load(run/'preregistration.json')
    numerical=load(run/'mc/preregistration.json')
    result=load(run/'result.json')
    report=load(run/'mc/report.json')
    previous=load(base/'t21_alternatives_5000_20260906_01/report.json')
    checks={}
    bindings = [('driver', prereg), ('numerical_child', numerical)]
    for owner, binding in bindings:
      for relative,expected in binding['source_hashes'].items():
        p=(root/relative).resolve()
        if not p.is_relative_to(root):
            raise ValueError('Unsafe source reference')
        checks['source:'+owner+':'+relative]=p.is_file() and sha(p)==expected
    checks['registered_base_probability_family'] = (
        numerical.get('probability_cost_scope') == 'BASE_ONLY'
        and numerical.get('risk_events') == ['daily_loss']
        and numerical.get('comparison_budget') == 4
        and numerical.get('family_alpha') == .05)
    checks['registered_frozen_workload'] = (
        numerical.get('paths') == 5000 and numerical.get('horizon_bars') == 72
        and numerical.get('block_bars') == 12 and numerical.get('costs') == [1, 2]
        and numerical.get('history') == 'FIXED_EXPOSED_LAST_30_DAYS'
        and numerical.get('financial_permission') is False)
    checks['frozen_full_path_budget']=prereg.get('paths')==5000 and report.get('completed')==5000
    checks['same_frozen_record_hash']=report.get('record_hash')==previous.get('record_hash') and bool(report.get('record_hash'))
    checks['archive_integrity']=sha(run/'mc/paths.jsonl.gz')==report.get('compressed_sha256')
    checks['owned_child_completed']=result.get('worker',{}).get('status')=='COMPLETED' and result.get('worker',{}).get('value',{}).get('exit_code')==0
    checks['protection_parity_observed']=result.get('synthetic_protection_parity') is True and type(result.get('protection_checks')) is int and result['protection_checks']>0
    checks['owned_resources_stopped']=result.get('child_stopped') is True and result.get('reader_stopped') is True
    checks['source_stable_during_run']=result.get('source_unchanged') is True and report.get('source_unchanged') is True
    return {'checks':checks,'engineering_artifacts_consistent':all(checks.values()),
            'scope':'ARCHIVED_INDEPENDENT_SYNTHETIC_WORKLOAD',
            'registered_probability_scope': {
                'events': numerical.get('risk_events'), 'cost_scope': numerical.get('probability_cost_scope'),
                'comparison_budget': numerical.get('comparison_budget'), 'family_alpha': numerical.get('family_alpha'),
                'family_alpha_is_not_a_trading_risk_limit': True},
            'unresolved':['FORMAL_RISK_EVENTS_AND_ADMISSION_THRESHOLDS_NOT_FROZEN',
                          'FULL_G4_SEMANTIC_AND_NUMERICAL_ACCEPTANCE_NOT_ESTABLISHED_BY_THIS_AUDIT'],
            'downstream_not_g4_prerequisites': ['AUTHENTICATED_VENUE_PROTECTION_AND_G8_ACCEPTANCE'],
            'G4_passed':False,'execution_allowed':False,
            'evidence_hashes':{str(p.relative_to(root)):sha(p) for p in
                (run/'preregistration.json',run/'mc/preregistration.json',run/'result.json',run/'mc/report.json')}}
