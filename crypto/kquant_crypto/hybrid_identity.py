"""Content-addressed M1 identities, deliberately separate from baseline IDs."""

import hashlib
import json


def _identity(kind, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return kind + '_' + hashlib.sha256(encoded).hexdigest()


def economic_signal_id(strategy_version, policy_hash, symbol, mode, signal_time, opportunity_sequence):
    if symbol not in {'BTCUSDT', 'ETHUSDT', 'SOLUSDT'} or mode not in {'UP_TREND', 'RANGE'}:
        raise ValueError('Unsupported baseline identity')
    if not strategy_version or not policy_hash:
        raise ValueError('Missing baseline version')
    if type(signal_time) is not int or signal_time < 0 or signal_time % 300:
        raise ValueError('Signal must identify a closed 5m boundary')
    if type(opportunity_sequence) is not int or opportunity_sequence < 0:
        raise ValueError('Invalid kernel opportunity sequence')
    return _identity('signal', [strategy_version, policy_hash, symbol, mode, signal_time, opportunity_sequence])


def evaluation_id(signal_id, frozen_evidence):
    if not signal_id.startswith('signal_') or not isinstance(frozen_evidence, dict) or not frozen_evidence:
        raise ValueError('Evaluation requires a signal and explicit frozen evidence')
    return _identity('evaluation', [signal_id, frozen_evidence])


def entry_intent_id(run_id, experiment_arm, signal_id):
    if not run_id or not experiment_arm or not signal_id.startswith('signal_'):
        raise ValueError('Missing isolated run, arm or signal')
    return _identity('intent', [run_id, experiment_arm, signal_id])
