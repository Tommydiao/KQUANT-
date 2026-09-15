"""Credential-free bounded loopback probe, not an execution health attestation."""
import json
import time
import httpx
from .hybrid_loopback_transport import LoopbackHealthTransport

URL = 'http://127.0.0.1:8010/api/health'


def probe(*, transport=None):
    started = time.monotonic()
    state, reason = 'UNKNOWN', 'INVALID_HEALTH_RESPONSE'
    code = None
    provider_report = 'NOT_OBSERVED'
    timings = {}
    budget_exceeded = False
    try:
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False,
                          transport=transport if transport is not None else LoopbackHealthTransport()) as client:
            timings['client_ready_seconds'] = time.monotonic()-started
            if timings['client_ready_seconds'] > 3:
                budget_exceeded = True
                raise ValueError('Client initialization exhausted budget')
            with client.stream('GET', URL) as response:
                timings['headers_seconds'] = time.monotonic()-started
                code = response.status_code
                if code == 200:
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started > 3:
                            budget_exceeded = True
                            raise ValueError('Total read budget exceeded')
                        raw.extend(chunk)
                        if len(raw) > 65536:
                            raise ValueError('Oversize')
                    payload = json.loads(raw)
                    timings['body_decoded_seconds'] = time.monotonic()-started
                    if isinstance(payload, dict) and payload.get('status') == 'ok':
                        state, reason = 'OK', 'HTTP_HEALTH_RESPONDED_ONLY'
                        providers = payload.get('providers')
                        binance = providers.get('binance') if isinstance(providers, dict) else None
                        if isinstance(binance, dict):
                            if binance.get('enabled') is False and binance.get('status') == 'disabled':
                                provider_report = 'API_RUNTIME_PROVIDER_DISABLED'
                            elif binance.get('status') in ('error', 'clock_skew', 'source_stale', 'resync_required'):
                                provider_report = 'API_RUNTIME_PROVIDER_DEGRADED'
                            else:
                                provider_report = 'API_RUNTIME_PROVIDER_UNVERIFIED'
                else:
                    state, reason = 'FAILED', 'HTTP_HEALTH_NOT_SUCCESSFUL'
    except httpx.HTTPError:
        state, reason = 'FAILED', 'LOCAL_HEALTH_UNREACHABLE'
    except (ValueError, UnicodeError):
        state, reason = 'UNKNOWN', ('LOCAL_PROBE_BUDGET_EXCEEDED' if budget_exceeded else 'INVALID_HEALTH_RESPONSE')
    now = int(time.time())
    observations = {'process': {'state': state, 'observed_at': now}}
    if provider_report == 'API_RUNTIME_PROVIDER_DISABLED':
        observations['data'] = {'state': 'WAITING', 'observed_at': now}
    elif provider_report == 'API_RUNTIME_PROVIDER_DEGRADED':
        observations['data'] = {'state': 'FAILED', 'observed_at': now}
    return {'observations': observations,
            'provider_report': provider_report,
            'provider_scope': 'API_RUNTIME_ONLY_NOT_INDEPENDENT_COLLECTORS',
            'observed_at': now, 'reason': reason, 'http_status': code,
            'elapsed_seconds': time.monotonic()-started,
            'phase_timings': timings,
            'scope': 'LOOPBACK_HTTP_RESPONSIVENESS_ONLY',
            'credentials_used': False, 'execution_authorized': False}
