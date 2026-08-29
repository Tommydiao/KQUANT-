from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


@dataclass(frozen=True)
class DexPairSnapshot:
    chain_id: str
    dex_id: str
    pair_address: str
    base_contract: str
    quote_contract: str
    base_symbol: str
    quote_symbol: str
    price_usd: float | None
    liquidity_usd: float | None
    volume_5m_usd: float | None
    buys_5m: int | None
    sells_5m: int | None
    pair_created_at: str | None
    source: str = "dexscreener"
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def asset_id(self) -> str:
        return f"{self.chain_id.lower()}:{self.base_contract.lower()}"

    @property
    def pool_id(self) -> str:
        return f"pool:{self.chain_id.lower()}:{self.pair_address.lower()}"

    @classmethod
    def from_dexscreener(cls, payload: dict[str, Any]) -> "DexPairSnapshot":
        chain_id = str(payload.get("chainId") or "").strip().lower()
        pair_address = str(payload.get("pairAddress") or "").strip().lower()
        base = payload.get("baseToken") or {}
        quote = payload.get("quoteToken") or {}
        base_contract = str(base.get("address") or "").strip().lower()
        quote_contract = str(quote.get("address") or "").strip().lower()
        if not all((chain_id, pair_address, base_contract, quote_contract)):
            raise ValueError("DEX pair requires chainId, pairAddress and both token contracts")

        def number(value: Any) -> float | None:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        txns = payload.get("txns") or {}
        five_minute = txns.get("m5") or {}
        return cls(
            chain_id=chain_id,
            dex_id=str(payload.get("dexId") or "unknown"),
            pair_address=pair_address,
            base_contract=base_contract,
            quote_contract=quote_contract,
            base_symbol=str(base.get("symbol") or "UNKNOWN"),
            quote_symbol=str(quote.get("symbol") or "UNKNOWN"),
            price_usd=number(payload.get("priceUsd")),
            liquidity_usd=number((payload.get("liquidity") or {}).get("usd")),
            volume_5m_usd=number((payload.get("volume") or {}).get("m5")),
            buys_5m=int(five_minute.get("buys")) if five_minute.get("buys") is not None else None,
            sells_5m=int(five_minute.get("sells")) if five_minute.get("sells") is not None else None,
            pair_created_at=str(payload.get("pairCreatedAt")) if payload.get("pairCreatedAt") is not None else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "pool_id": self.pool_id,
            "chain_id": self.chain_id,
            "dex_id": self.dex_id,
            "pair_address": self.pair_address,
            "base_contract": self.base_contract,
            "quote_contract": self.quote_contract,
            "base_symbol": self.base_symbol,
            "quote_symbol": self.quote_symbol,
            "price_usd": self.price_usd,
            "liquidity_usd": self.liquidity_usd,
            "volume_5m_usd": self.volume_5m_usd,
            "buys_5m": self.buys_5m,
            "sells_5m": self.sells_5m,
            "pair_created_at": self.pair_created_at,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True)
class TokenSecurityInput:
    asset_id: str
    chain_id: str
    source: str
    provider_status: str
    honeypot: bool | None = None
    sell_enabled: bool | None = None
    buy_tax: float | None = None
    sell_tax: float | None = None
    blacklist: bool | None = None
    can_pause: bool | None = None
    can_mint: bool | None = None
    can_freeze: bool | None = None
    lp_locked: bool | None = None
    top10_concentration: float | None = None
    liquidity_usd: float | None = None
    holder_count: int | None = None
    creator_share: float | None = None
    lp_share: float | None = None


@dataclass(frozen=True)
class TokenSecurityDecision:
    status: str
    risk_level: str
    blockers: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    checked_fields: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "risk_level": self.risk_level,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "checked_fields": list(self.checked_fields),
        }


def assess_token_security(value: TokenSecurityInput) -> TokenSecurityDecision:
    if value.provider_status.lower() not in {"live", "available", "passed"}:
        return TokenSecurityDecision("unknown", "unknown", (), ({"code": "security_provider_unavailable"},), ())
    required = {
        "honeypot": value.honeypot,
        "sell_enabled": value.sell_enabled,
        "buy_tax": value.buy_tax,
        "sell_tax": value.sell_tax,
        "blacklist": value.blacklist,
        "lp_locked": value.lp_locked,
    }
    if any(item is None for item in required.values()):
        return TokenSecurityDecision("unknown", "unknown", (), ({"code": "security_field_missing"},), tuple(key for key, item in required.items() if item is not None))
    blockers: list[dict[str, Any]] = []
    if value.honeypot:
        blockers.append({"code": "honeypot", "message": "token is reported as unsellable"})
    if value.sell_enabled is False:
        blockers.append({"code": "sell_disabled", "message": "selling is disabled or not verified"})
    if (value.buy_tax or 0) > 0.10 or (value.sell_tax or 0) > 0.10:
        blockers.append({"code": "high_tax", "message": "buy or sell tax exceeds the safety limit"})
    if value.blacklist:
        blockers.append({"code": "blacklist_control", "message": "blacklist control is enabled"})
    if value.can_pause or value.can_mint or value.can_freeze:
        blockers.append({"code": "dangerous_admin_permission", "message": "dangerous token administration permission is enabled"})
    if value.lp_locked is False:
        blockers.append({"code": "lp_unlocked", "message": "liquidity lock was not verified"})
    warnings: list[dict[str, Any]] = []
    if value.top10_concentration is not None and value.top10_concentration > 0.50:
        warnings.append({"code": "holder_concentration_high"})
    if value.liquidity_usd is not None and value.liquidity_usd < 50_000:
        warnings.append({"code": "liquidity_low"})
    return TokenSecurityDecision(
        "blocked" if blockers else "passed",
        "high" if blockers else ("medium" if warnings else "low"),
        tuple(blockers),
        tuple(warnings),
        tuple(required),
    )


class DexSecurityStore:
    def __init__(self, db_path):
        self.db_path = db_path

    def save_security(self, value: TokenSecurityInput, decision: TokenSecurityDecision, *, source_time: str | None = None, _migrate: bool = True) -> dict[str, Any]:
        if _migrate:
            migrate(self.db_path)
        payload = {"input": value.__dict__, "decision": decision.as_dict()}
        # Holder ownership changes are stored as their own time series. They
        # must not turn an otherwise identical token-safety decision into a
        # duplicate security event on every refresh.
        security_input = dict(value.__dict__)
        for field_name in ("holder_count", "creator_share", "lp_share", "top10_concentration"):
            security_input.pop(field_name, None)
        digest = stable_hash({"input": security_input, "decision": decision.as_dict()})
        snapshot_id = f"security_{uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        with connect(self.db_path) as conn:
            existing = conn.execute("SELECT security_snapshot_id FROM crypto_token_security_snapshots WHERE content_hash=?", (digest,)).fetchone()
            if existing is not None:
                return {"security_snapshot_id": existing["security_snapshot_id"], "asset_id": value.asset_id, "status": decision.status, "risk_level": decision.risk_level, "content_hash": digest, "payload": payload, "deduplicated": True}
            conn.execute(
                "INSERT INTO crypto_token_security_snapshots(security_snapshot_id,asset_id,chain_id,source,source_time,available_at,fetched_at,status,risk_level,content_hash,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (snapshot_id, value.asset_id, value.chain_id, value.source, source_time, now, now, decision.status, decision.risk_level, digest, json.dumps(payload, ensure_ascii=True, sort_keys=True)),
            )
            if any(item is not None for item in (value.holder_count, value.top10_concentration, value.creator_share, value.lp_share)):
                conn.execute(
                    """
                    INSERT INTO crypto_holder_snapshots(
                      holder_snapshot_id,asset_id,source,source_time,holder_count,
                      top10_concentration,creator_share,lp_share,payload_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"holder_{uuid4().hex}", value.asset_id, value.source, source_time,
                        value.holder_count, value.top10_concentration, value.creator_share,
                        value.lp_share, json.dumps(payload, ensure_ascii=True, sort_keys=True), now,
                    ),
                )
        return {"security_snapshot_id": snapshot_id, "asset_id": value.asset_id, "status": decision.status, "risk_level": decision.risk_level, "content_hash": digest, "payload": payload, "deduplicated": False}

    def latest_holder(self, asset_id: str) -> dict[str, Any] | None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM crypto_holder_snapshots WHERE asset_id=? ORDER BY source_time DESC, created_at DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value


class DexMarketStore:
    """Persist DEX discovery snapshots without treating them as trade permission."""

    def __init__(self, db_path):
        self.db_path = db_path

    def save_pair(self, value: DexPairSnapshot, *, trust_status: str = "live", _migrate: bool = True) -> dict[str, Any]:
        if _migrate:
            migrate(self.db_path)
        with connect(self.db_path) as conn:
            return self._save_pair_in_connection(conn, value, trust_status=trust_status)

    def save_pairs(
        self,
        values: list[DexPairSnapshot],
        *,
        trust_status: str = "live",
        _migrate: bool = True,
    ) -> list[dict[str, Any]]:
        """Persist one discovery response in a single SQLite transaction."""

        if _migrate:
            migrate(self.db_path)
        with connect(self.db_path) as conn:
            return [self._save_pair_in_connection(conn, value, trust_status=trust_status) for value in values]

    @staticmethod
    def _save_pair_in_connection(conn, value: DexPairSnapshot, *, trust_status: str) -> dict[str, Any]:
        now = value.fetched_at
        payload = value.as_dict()
        content_hash = stable_hash({key: item for key, item in payload.items() if key != "fetched_at"})
        effective_from = value.pair_created_at or now
        for asset_id, address, symbol in (
            (value.asset_id, value.base_contract, value.base_symbol),
            (f"{value.chain_id}:{value.quote_contract}", value.quote_contract, value.quote_symbol),
        ):
            conn.execute(
                """
                INSERT INTO crypto_token_contracts(
                  asset_id,chain_id,contract_address,symbol,name,status,
                  first_seen_at,last_seen_at,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET
                  symbol=excluded.symbol,last_seen_at=excluded.last_seen_at,
                  metadata_json=excluded.metadata_json
                """,
                (asset_id, value.chain_id, address, symbol, symbol, "active", now, now, json.dumps({"source": value.source}, sort_keys=True)),
            )
        conn.execute(
            """
            INSERT INTO crypto_liquidity_pools(
              pool_id,chain_id,dex_id,pair_address,base_asset_id,quote_asset_id,
              created_at_source,status,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(pool_id) DO UPDATE SET
              dex_id=excluded.dex_id,status='active',metadata_json=excluded.metadata_json
            """,
            (value.pool_id, value.chain_id, value.dex_id, value.pair_address, value.asset_id, f"{value.chain_id}:{value.quote_contract}", value.pair_created_at, "active", json.dumps({"source": value.source}, sort_keys=True)),
        )
        for asset_id in (value.asset_id, f"{value.chain_id}:{value.quote_contract}"):
            conn.execute(
                """
                INSERT OR IGNORE INTO crypto_token_pool_memberships(
                  pool_id,asset_id,effective_from,effective_to,membership_status
                ) VALUES(?,?,?,?,?)
                """,
                (value.pool_id, asset_id, effective_from, None, "active"),
            )
        existing = conn.execute("SELECT snapshot_id FROM crypto_dex_market_snapshots WHERE content_hash=?", (content_hash,)).fetchone()
        if existing is not None:
            return {"snapshot_id": existing["snapshot_id"], "pool_id": value.pool_id, "asset_id": value.asset_id, "content_hash": content_hash, "deduplicated": True}
        snapshot_id = f"dex_{uuid4().hex}"
        conn.execute(
            """
            INSERT INTO crypto_dex_market_snapshots(
              snapshot_id,pool_id,source,source_time,available_at,fetched_at,trust_status,
              price_usd,liquidity_usd,volume_5m_usd,buys_5m,sells_5m,fdv_usd,content_hash,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (snapshot_id, value.pool_id, value.source, now, now, now, trust_status, value.price_usd, value.liquidity_usd, value.volume_5m_usd, value.buys_5m, value.sells_5m, None, content_hash, json.dumps(payload, ensure_ascii=True, sort_keys=True)),
        )
        return {"snapshot_id": snapshot_id, "pool_id": value.pool_id, "asset_id": value.asset_id, "content_hash": content_hash, "deduplicated": False}
