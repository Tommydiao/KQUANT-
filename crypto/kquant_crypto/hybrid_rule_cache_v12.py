"""Explicit development rule versions. No network fetching or execution admission."""
from dataclasses import dataclass
from .hybrid_mock_broker import SymbolRules, BrokerRejected


@dataclass(frozen=True)
class RuleSnapshot:
    rules: SymbolRules
    available_at: int
    environment: str
    source: str

    def __post_init__(self):
        if not isinstance(self.rules, SymbolRules):
            raise ValueError('Validated rule object required')
        if type(self.available_at) is not int or not 0 <= self.available_at < self.rules.valid_until:
            raise ValueError('Explicit availability before expiry required')
        if self.environment != 'mock' or self.source != 'SYNTHETIC_RULE_FIXTURE':
            raise ValueError('Actual venue normalization not integrated')


class RuleCache:
    def __init__(self):
        self.versions = {}
        self.current = {}

    def put(self, snapshot):
        if not isinstance(snapshot, RuleSnapshot):
            raise ValueError('Rule snapshot required')
        key = (snapshot.environment, snapshot.rules.symbol)
        previous = self.current.get(key)
        if previous and snapshot.available_at < previous.available_at:
            raise ValueError('Older refresh cannot replace current rules')
        if previous and snapshot.available_at == previous.available_at and snapshot != previous:
            raise ValueError('Conflicting same-time rules')
        identity = (key, snapshot.rules.rule_hash)
        old = self.versions.get(identity)
        if old and old != snapshot:
            raise ValueError('Rule version metadata is immutable')
        self.versions[identity] = snapshot
        self.current[key] = snapshot

    def get(self, symbol, *, now, expected_hash, environment='mock'):
        if type(now) is not int or now < 0:
            raise ValueError('Explicit current time required')
        snapshot = self.current.get((environment, symbol))
        if snapshot is None:
            raise BrokerRejected('rules unavailable')
        if not snapshot.available_at <= now <= snapshot.rules.valid_until:
            raise BrokerRejected('rules stale or not yet available')
        if snapshot.rules.rule_hash != expected_hash:
            raise BrokerRejected('plan rules version changed; reevaluate')
        if not snapshot.rules.trading:
            raise BrokerRejected('trading disabled')
        return snapshot.rules
