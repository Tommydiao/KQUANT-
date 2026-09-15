import hashlib
import json
from kquant_crypto.hybrid_mc_evidence_audit import audit_mc_engineering


def test_consistent_artifacts_do_not_authorize_gate(tmp_path):
    base=tmp_path/'outputs/hybrid_delivery'
    run=base/'mc_process_load_20260906_03'
    (run/'mc').mkdir(parents=True)
    old=base/'t21_alternatives_5000_20260906_01'
    old.mkdir()
    source=tmp_path/'source.py'
    source.write_bytes(b'fixture')
    digest=hashlib.sha256(b'fixture').hexdigest()
    (run/'mc/paths.jsonl.gz').write_bytes(b'fixture')
    def put(p,obj): p.write_text(json.dumps(obj))
    put(run/'preregistration.json',{'paths':5000,'source_hashes':{'source.py':digest}})
    child=tmp_path/'numerical.py'
    child.write_bytes(b'fixture')
    put(run/'mc/preregistration.json',{'source_hashes':{'numerical.py':digest},
        'probability_cost_scope':'BASE_ONLY','risk_events':['daily_loss'],
        'comparison_budget':4,'family_alpha':.05,'paths':5000,'horizon_bars':72,
        'block_bars':12,'costs':[1,2],'history':'FIXED_EXPOSED_LAST_30_DAYS','financial_permission':False})
    put(run/'result.json',{'worker':{'status':'COMPLETED','value':{'exit_code':0}},
        'synthetic_protection_parity':True,'protection_checks':480,
        'child_stopped':True,'reader_stopped':True,'source_unchanged':True})
    put(run/'mc/report.json',{'completed':5000,'record_hash':digest,
        'compressed_sha256':digest,'source_unchanged':True})
    put(old/'report.json',{'record_hash':digest})
    report=audit_mc_engineering(tmp_path)
    assert report['engineering_artifacts_consistent']
    assert not report['G4_passed'] and not report['execution_allowed']
    assert report['registered_probability_scope']['family_alpha_is_not_a_trading_risk_limit']
    assert 'AUTHENTICATED_VENUE_PROTECTION_AND_G8_ACCEPTANCE' in report['downstream_not_g4_prerequisites']
    child.write_bytes(b'changed')
    assert not audit_mc_engineering(tmp_path)['engineering_artifacts_consistent']
