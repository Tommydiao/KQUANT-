"""Credential-reference validation for future Spot Testnet engineering.

No secrets, network client, production execution or self-issued owner approval.
This module cannot authorize a request. It can reject an invalid configuration.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CredentialReference:
    reference: str
    environment: str
    service_entity: str
    permissions: frozenset[str]


def inspect_configuration(*, environment, endpoint, reference, actor='coding_agent'):
    if environment not in ('disabled','mock','testnet','production_readonly','live'):
        raise ValueError('Unknown environment')
    if environment in ('live','production_readonly'):
        return {'status':'DENIED','reason':'Production access requires independent owner-controlled runtime; unavailable to this developer adapter',
                'request_authorized':False,'trade_authorized':False}
    if environment in ('disabled','mock'):
        if reference is not None or endpoint is not None:
            raise ValueError('Disabled/mock mode has no endpoint or credential')
        return {'status':'LOCAL_ONLY','request_authorized':False,'trade_authorized':False}
    if not isinstance(reference,CredentialReference) or reference.environment!='testnet':
        raise ValueError('Testnet-only credential reference required')
    if not reference.reference or len(reference.reference)>128:
        raise ValueError('Opaque owner-provisioned reference required, not a key')
    if reference.service_entity!='BINANCE_SPOT_TESTNET':
        raise ValueError('Do not confuse Binance entities, products or epochs')
    if not reference.permissions<=frozenset({'USER_DATA','TRADE'}):
        raise ValueError('Withdraw/transfer/margin/derivative permissions forbidden')
    u=urlsplit(endpoint or '')
    if (u.scheme!='https' or u.hostname!='testnet.binance.vision' or u.port not in (None,443)
            or u.username or u.password or u.query or u.fragment or u.path not in ('','/')):
        raise ValueError('Explicit Spot Testnet origin only, no public-data or production fallback')
    if actor not in ('coding_agent','test_harness'):
        raise ValueError('Unknown development actor')
    return {'status':'CONFIGURATION_VALID_NOT_CONNECTED','request_authorized':False,'trade_authorized':False,
            'required_next':'Applicable A1 Testnet approval, protected test credentials and separate endpoint implementation',
            'environment':'testnet','service_entity':reference.service_entity,'credentials_loaded':False}
