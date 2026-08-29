from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .universe_catalog import DEFAULT_CEX_SYMBOLS, configured_cex_symbols


APP_VERSION = "0.3.3"
API_CONTRACT_VERSION = "kquant-crypto-api-2026-08-24-evidence-v5"
FRONTEND_CONTRACT_VERSION = "kquant-crypto-web-2026-08-23-roll-research-v1"


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    SHADOW = "shadow"


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(root: Path, env_name: str, default: str) -> Path:
    raw = Path(os.getenv(env_name, default))
    return raw if raw.is_absolute() else root / raw


def _load_dotenv(root: Path) -> None:
    """Load local development values without overriding the process env."""

    path = root / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


@dataclass(frozen=True)
class ProviderFlags:
    binance: bool = False
    okx: bool = False
    coinbase: bool = False
    kraken: bool = False
    dexscreener: bool = False
    goplus: bool = False
    birdeye: bool = False
    coinglass: bool = False
    defillama: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "binance": self.binance,
            "okx": self.okx,
            "coinbase": self.coinbase,
            "kraken": self.kraken,
            "dexscreener": self.dexscreener,
            "goplus": self.goplus,
            "birdeye": self.birdeye,
            "coinglass": self.coinglass,
            "defillama": self.defillama,
        }


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    mode: RuntimeMode
    host: str
    port: int
    db_path: Path
    data_dir: Path
    outputs_dir: Path
    web_dist_dir: Path
    login_email: str
    login_password_hash: str
    session_secret: str
    session_idle_minutes: int
    session_max_hours: int
    notifications_enabled: bool
    telegram_enabled: bool
    providers: ProviderFlags
    core_symbols: tuple[str, ...] = DEFAULT_CEX_SYMBOLS
    high_frequency_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    web_push_public_key: str = ""
    web_push_private_key: str = ""
    web_push_subject: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    goplus_api_key: str = ""
    coinglass_api_key: str = ""
    etf_evidence_url: str = ""
    onchain_evidence_url: str = ""
    staging_database_url: str = ""
    market_trade_bucket_seconds: int = 60
    market_quote_sample_seconds: float = 5.0
    market_ticker_sample_seconds: float = 10.0
    market_storage_flush_every: int = 5000

    @property
    def auth_configured(self) -> bool:
        return bool(self.login_email and self.login_password_hash and self.session_secret)


def load_settings(root_dir: Path | None = None) -> Settings:
    root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
    _load_dotenv(root)
    raw_mode = os.getenv("KQUANT_CRYPTO_MODE", RuntimeMode.DEVELOPMENT.value).lower()
    try:
        mode = RuntimeMode(raw_mode)
    except ValueError as exc:
        raise ValueError(f"Unsupported KQUANT_CRYPTO_MODE: {raw_mode}") from exc
    port = int(os.getenv("KQUANT_CRYPTO_PORT", "8010"))
    if not 1 <= port <= 65535:
        raise ValueError("KQUANT_CRYPTO_PORT must be between 1 and 65535.")
    providers = ProviderFlags(
        binance=_bool("KQUANT_CRYPTO_ENABLE_BINANCE"),
        okx=_bool("KQUANT_CRYPTO_ENABLE_OKX"),
        coinbase=_bool("KQUANT_CRYPTO_ENABLE_COINBASE"),
        kraken=_bool("KQUANT_CRYPTO_ENABLE_KRAKEN"),
        dexscreener=_bool("KQUANT_CRYPTO_ENABLE_DEXSCREENER"),
        goplus=_bool("KQUANT_CRYPTO_ENABLE_GOPLUS"),
        birdeye=_bool("KQUANT_CRYPTO_ENABLE_BIRDEYE"),
        coinglass=_bool("KQUANT_CRYPTO_ENABLE_COINGLASS"),
        defillama=_bool("KQUANT_CRYPTO_ENABLE_DEFILLAMA"),
    )
    default_symbols = configured_cex_symbols(root)
    settings = Settings(
        root_dir=root,
        mode=mode,
        host=os.getenv("KQUANT_CRYPTO_HOST", "127.0.0.1"),
        port=port,
        db_path=_path(root, "KQUANT_CRYPTO_DB_PATH", "work/kquant_crypto.sqlite3"),
        data_dir=_path(root, "KQUANT_CRYPTO_DATA_DIR", "data"),
        outputs_dir=_path(root, "KQUANT_CRYPTO_OUTPUTS_DIR", "outputs"),
        web_dist_dir=root / "web" / "dist",
        login_email=os.getenv("KQUANT_CRYPTO_LOGIN_EMAIL", "").strip().lower(),
        login_password_hash=os.getenv("KQUANT_CRYPTO_LOGIN_PASSWORD_HASH", "").strip(),
        session_secret=os.getenv("KQUANT_CRYPTO_SESSION_SECRET", "").strip(),
        session_idle_minutes=max(5, int(os.getenv("KQUANT_CRYPTO_SESSION_IDLE_MINUTES", "30"))),
        session_max_hours=max(1, int(os.getenv("KQUANT_CRYPTO_SESSION_MAX_HOURS", "8"))),
        notifications_enabled=_bool("KQUANT_CRYPTO_ENABLE_NOTIFICATIONS"),
        telegram_enabled=_bool("KQUANT_CRYPTO_ENABLE_TELEGRAM"),
        providers=providers,
        core_symbols=tuple(
            value.strip().upper()
            for value in os.getenv("KQUANT_CRYPTO_CORE_SYMBOLS", ",".join(default_symbols)).split(",")
            if value.strip()
        ),
        high_frequency_symbols=tuple(
            value.strip().upper()
            for value in os.getenv("KQUANT_CRYPTO_HIGH_FREQUENCY_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
            if value.strip()
        ),
        web_push_public_key=os.getenv("KQUANT_CRYPTO_WEB_PUSH_PUBLIC_KEY", "").strip(),
        web_push_private_key=os.getenv("KQUANT_CRYPTO_WEB_PUSH_PRIVATE_KEY", "").strip(),
        web_push_subject=os.getenv("KQUANT_CRYPTO_WEB_PUSH_SUBJECT", "").strip(),
        telegram_bot_token=os.getenv("KQUANT_CRYPTO_TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("KQUANT_CRYPTO_TELEGRAM_CHAT_ID", "").strip(),
        goplus_api_key=os.getenv("GOPLUS_API_KEY", "").strip(),
        coinglass_api_key=os.getenv("COINGLASS_API_KEY", "").strip(),
        etf_evidence_url=os.getenv("KQUANT_CRYPTO_ETF_EVIDENCE_URL", "").strip(),
        onchain_evidence_url=os.getenv("KQUANT_CRYPTO_ONCHAIN_EVIDENCE_URL", "").strip(),
        staging_database_url=os.getenv("KQUANT_CRYPTO_STAGING_DATABASE_URL", "").strip(),
        market_trade_bucket_seconds=max(1, int(os.getenv("KQUANT_CRYPTO_TRADE_BUCKET_SECONDS", "60"))),
        market_quote_sample_seconds=max(0.0, float(os.getenv("KQUANT_CRYPTO_QUOTE_SAMPLE_SECONDS", "5"))),
        market_ticker_sample_seconds=max(0.0, float(os.getenv("KQUANT_CRYPTO_TICKER_SAMPLE_SECONDS", "10"))),
        market_storage_flush_every=max(1, int(os.getenv("KQUANT_CRYPTO_STORAGE_FLUSH_EVERY", "5000"))),
    )
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    return settings
