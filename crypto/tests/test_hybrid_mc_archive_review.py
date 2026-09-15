import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('mc_review', Path(__file__).resolve().parents[1] / 'scripts/review_hybrid_mc_events.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def archive(tmp_path, rows):
    data = ''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows)
    p = tmp_path / 'paths.jsonl.gz'
    with gzip.open(p, 'wt') as f:
        f.write(data)
    return {'compressed_sha256':m.sha(p), 'record_hash':hashlib.sha256(data.replace('\n','').encode()).hexdigest(), 'completed':len(rows)}


def row(i):
    return {'path_id':i, 'costs':{f'{a}:{c}':{'risk':{'terminal_net_change':-1}} for a in (0,.25,.5,1) for c in (1,2)}}


def test_valid_and_modified_digest(tmp_path):
    original = archive(tmp_path, [row(0)])
    events = [m.RiskEvent('loss','terminal_net_change',0)]
    assert m.read_archive(tmp_path, original, events)[1] == [0]
    original['record_hash'] = '0'*64
    with pytest.raises(ValueError, match='identity'):
        m.read_archive(tmp_path, original, events)


@pytest.mark.parametrize('kind',['duplicate','missing_cost','bool_id','empty'])
def test_invalid_structure(tmp_path,kind):
    rows = [row(0),row(1)]
    if kind == 'duplicate': rows[1]['path_id'] = 0
    if kind == 'missing_cost': del rows[0]['costs']['0:2']
    if kind == 'bool_id': rows[0]['path_id'] = False
    if kind == 'empty': rows=[]
    original=archive(tmp_path,rows)
    with pytest.raises(ValueError):
        m.read_archive(tmp_path,original,[m.RiskEvent('loss','terminal_net_change',0)])
