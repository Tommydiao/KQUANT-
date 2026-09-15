"""Explicit per-factor provenance for already computed research snapshots."""
import hashlib
import json
import math
from .hybrid_multifactor_dev import DEFINITIONS, CROSS_DEFINITIONS
from .hybrid_trend_features import TREND_DEFINITIONS
from .hybrid_dependence_features import DEPENDENCE_DEFINITIONS


def factor_records(row):
    source = row['source']
    records = []
    groups = [(row, DEFINITIONS), (row['cross_section'], CROSS_DEFINITIONS)]
    if 'trend' in row:
        groups.append((row['trend'], TREND_DEFINITIONS))
    if 'dependence' in row:
        groups.append((row['dependence'], DEPENDENCE_DEFINITIONS))
    for snapshot, definitions in groups:
        for name, formula in definitions.items():
            value = snapshot['values'].get(name)
            available = (snapshot['status'] == 'AVAILABLE' and value is not None
                         and isinstance(value, (int, float)) and math.isfinite(value))
            records.append({
                'factor_id':name, 'formula':formula, 'version':snapshot.get('version','multifactor_ohlcv_dev_v1'),
                'source':source, 'timeframe':'1h', 'as_of':row['as_of'],
                'available_at':row['available_at'],
                'availability_basis':row['availability_basis'],
                'status':'AVAILABLE' if available else 'MISSING',
                'missing_reason':None if available else ('ZERO_OR_MISSING_DENOMINATOR'
                    if snapshot['status']=='AVAILABLE' else snapshot['status']),
                'value':value if available else None})
    canonical = {'symbol':row['symbol'],'dataset_hash':row['dataset_hash'],'factors':records}
    canonical['factor_snapshot_hash'] = hashlib.sha256(json.dumps(
        canonical,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    return canonical
