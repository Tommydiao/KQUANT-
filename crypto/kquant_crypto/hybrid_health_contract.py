"""Bounded, secret-free health summaries; no trading or notification authority."""
import hashlib
import json

COMPONENTS = ('data', 'model', 'orders', 'protection', 'process')
STATES = ('OK', 'WAITING', 'FAILED', 'UNKNOWN')


def summarize_health(observations, *, now, max_age):
    if type(now) is not int or now < 0 or type(max_age) is not int or max_age < 0:
        raise ValueError('Explicit nonnegative observation clock required')
    if not isinstance(observations, dict):
        raise ValueError('Component observations required')
    components = {}
    for name in COMPONENTS:
        value = observations.get(name)
        state, reason = 'UNKNOWN', 'NO_EVIDENCE'
        at = None
        if isinstance(value, dict):
            at = value.get('observed_at')
            if type(at) is not int or at < 0:
                at, reason = None, 'INVALID_TIME'
            elif at > now:
                reason = 'FUTURE_OBSERVATION'
            elif now - at > max_age:
                reason = 'STALE_OBSERVATION'
            elif value.get('state') not in STATES:
                reason = 'INVALID_STATE'
            else:
                state, reason = value['state'], 'REPORTED_STATE'
        # Only allowlisted scalar fields survive; raw errors/URLs/credentials never do.
        components[name] = {'state': state, 'reason': reason, 'observed_at': at}
    material = {key: {field: item[field] for field in ('state', 'reason')}
                for key, item in components.items()}
    encoded = json.dumps(material, sort_keys=True, separators=(',', ':')).encode()
    return {'components': components,
            'status': 'ATTENTION' if any(v['state'] != 'OK' for v in components.values()) else 'REPORTED_OK',
            'material_state_hash': hashlib.sha256(encoded).hexdigest(),
            'clock_scope': 'CALLER_OBSERVATION_CLOCK_NOT_EXCHANGE_TIME',
            'execution_authorized': False, 'external_notification_sent': False}
