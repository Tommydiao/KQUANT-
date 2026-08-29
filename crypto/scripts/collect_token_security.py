from __future__ import annotations

import argparse
import json

from kquant_crypto.config import load_settings
from kquant_crypto.dex_models import DexSecurityStore, assess_token_security
from kquant_crypto.providers.goplus import GoPlusPublicAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one read-only token security snapshot.")
    parser.add_argument("chain_id")
    parser.add_argument("contract_address")
    args = parser.parse_args()
    settings = load_settings()
    value = GoPlusPublicAdapter(api_key=settings.goplus_api_key).inspect(args.chain_id, args.contract_address)
    decision = assess_token_security(value)
    saved = DexSecurityStore(settings.db_path).save_security(value, decision)
    print(json.dumps({"asset_id": value.asset_id, "provider_status": value.provider_status, "status": decision.status, "risk_level": decision.risk_level, "security_snapshot_id": saved["security_snapshot_id"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
