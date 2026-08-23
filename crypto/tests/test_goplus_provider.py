from __future__ import annotations

import json

from kquant_crypto.providers.goplus import GoPlusPublicAdapter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_goplus_maps_security_fields_without_guessing_unknown_values():
    def opener(request, timeout):
        assert "/api/v1/token_security/1" in request.full_url
        assert timeout == 10.0
        return FakeResponse({"code": 1, "result": {"0xAb": {
            "is_honeypot": "0", "cannot_sell_all": "0", "buy_tax": "0.02", "sell_tax": "0.03",
            "is_blacklisted": "0", "transfer_pausable": "0", "is_mintable": "0",
            "lp_holders": [{"is_locked": "1"}], "holders": [{"percent": "0.2"}],
            "dex": [{"liquidity": "125000"}], "holder_count": "42", "creator_percent": "0.08",
        }}})

    value = GoPlusPublicAdapter(api_key="secret-not-returned", opener=opener).inspect("1", "0xAb")
    assert value.provider_status == "live"
    assert value.honeypot is False
    assert value.buy_tax == 0.02
    assert value.lp_locked is True
    assert value.liquidity_usd == 125000
    assert value.holder_count == 42
    assert value.creator_share == 0.08


def test_goplus_missing_result_is_unavailable():
    value = GoPlusPublicAdapter(opener=lambda *_args, **_kwargs: FakeResponse({"code": 0, "result": {}})).inspect("solana", "TOKEN")
    assert value.provider_status == "unavailable"
    assert value.asset_id == "solana:token"


def test_goplus_maps_dex_chain_names_to_numeric_security_paths():
    def opener(request, timeout):
        assert "/api/v1/token_security/8453" in request.full_url
        return FakeResponse({"code": 0, "result": {}})

    value = GoPlusPublicAdapter(opener=opener).inspect("base", "0xToken")
    assert value.provider_status == "unavailable"
    assert value.asset_id == "base:0xtoken"


def test_goplus_transport_failure_is_fail_closed():
    def opener(*_args, **_kwargs):
        raise OSError("offline")

    value = GoPlusPublicAdapter(opener=opener).inspect("1", "0xToken")
    assert value.provider_status == "unavailable"
