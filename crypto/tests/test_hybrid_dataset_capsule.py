import gzip
import json
import pytest
from kquant_crypto.hybrid_dataset import Dataset, SYMBOLS, file_hash
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.candidate_policy import digest
from kquant_crypto.hybrid_dataset_capsule import export_capsule, load_capsule


def fixture():
    start = 1754006400
    bars, provenance = {}, {}
    for symbol in SYMBOLS:
        bars[symbol] = {'5m':[Bar(start+i*300,100,102,99,101,1) for i in range(12)],
                        '1h':[Bar(start,100,102,99,101,12)]}
        provenance[symbol] = {tf:{b.start:dict(available_at=b.start+duration,
            availability_basis='assumed_close_historical_replay', received_at=9999999999,
            provider_status='historical', receipt_variants=['9999999999']) for b in bars[symbol][tf]}
            for tf,duration in (('5m',300),('1h',3600))}
    manifest = dict(symbols=list(SYMBOLS), window=dict(start=start, warmup_start=start, days=365))
    manifest['manifest_hash'] = digest(manifest)
    content = digest({s:{tf:[vars(b) for b in rows] for tf,rows in frames.items()} for s,frames in bars.items()})
    return Dataset(bars, provenance, manifest, [], start+3600, content)


def test_roundtrip_preserves_receipts_and_refuses_overwrite(tmp_path):
    data = fixture()
    out = tmp_path/'capsule'
    export_capsule(data, out)
    assert load_capsule(out) == data
    with pytest.raises(FileExistsError):
        export_capsule(data, out)


@pytest.mark.parametrize('change', ['hash', 'outside', 'tail_cutoff', 'unsafe'])
def test_invalid_capsule_rejected(tmp_path, change):
    out = tmp_path/'capsule'
    c = export_capsule(fixture(), out)
    entry = c['files']['BTCUSDT']['5m']
    path = out/entry['path']
    if change in ('hash', 'outside'):
        rows = json.loads(gzip.decompress(path.read_bytes()))
        rows[-1]['start'] += 3600
        path.write_bytes(gzip.compress(json.dumps(rows).encode(), mtime=0))
        if change == 'outside': entry['sha256'] = file_hash(path)
    if change == 'tail_cutoff': c['cutoff'] += 365*86400
    if change == 'unsafe': c['execution_enabled'] = True
    c['capsule_hash'] = digest({k:v for k,v in c.items() if k != 'capsule_hash'})
    (out/'capsule.json').write_text(json.dumps(c))
    with pytest.raises(ValueError):
        load_capsule(out)
