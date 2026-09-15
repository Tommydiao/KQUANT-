"""Receipt logging for new observers; the legacy frozen script is untouched."""
import asyncio
from datetime import datetime, UTC
import hashlib
import time

from .candidate_forward import REST_URL
from .hybrid_clock import POLICY, native_ms


async def probes(client, record=None):
    results = []
    for i in range(POLICY['probes']):
        m0 = time.perf_counter()
        l0 = time.time()
        try:
            response = await client.get(REST_URL + '/api/v3/time',
                headers={'Cache-Control':'no-cache', 'Pragma':'no-cache'})
            l1 = time.time()
            m1 = time.perf_counter()
            response.raise_for_status()
            server = response.json()['serverTime']
            converted = native_ms(server)
            sample = {'index':i, 'serverTime':server,
                'server_time_utc':datetime.fromtimestamp(converted,UTC).isoformat(),
                'monotonic_before':m0, 'monotonic_after':m1,
                'local_before':l0, 'local_after':l1, 'rtt':m1-m0,
                'local_before_utc':datetime.fromtimestamp(l0,UTC).isoformat(),
                'local_after_utc':datetime.fromtimestamp(l1,UTC).isoformat(),
                'server_minus_local_lower':converted-l1,'server_minus_local_upper':converted-l0,
                'age_seconds':float(response.headers.get('Age','0')),
                'response_headers':{k:response.headers.get(k) for k in ('date','age','cache-control','x-cache','content-type')},
                'response_sha256':hashlib.sha256(response.content).hexdigest(),
                'native_unit':'MILLISECOND','request_time_unit_header':None,'endpoint':str(response.url)}
        except Exception as exc:
            if record is not None:
                record({'index':i,'state':'FAILED','error_type':type(exc).__name__,
                    'monotonic_before':m0,'monotonic_after':time.perf_counter(),
                    'local_before':l0,'local_after':time.time()})
            raise
        results.append(sample)
        if record is not None:
            record({'state':'RECEIVED','sample':sample})
        await asyncio.sleep(.15)
    return results
