from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Literal


UniverseName = Literal["default", "ai", "ai_five_layer", "all"]


@dataclass(frozen=True)
class StockMeta:
    symbol: str
    name: str
    sector: str
    layer: str
    tags: tuple[str, ...]
    rank: int
    liquidity_tier: str = "core"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        payload["primary_layer"] = self.layer
        return payload


_RAW_STOCKS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("SPY", "SPDR S&P 500 ETF", "ETF", "Index ETFs", ("index", "liquid")),
    ("QQQ", "Invesco QQQ Trust", "ETF", "Index ETFs", ("index", "growth")),
    ("IWM", "iShares Russell 2000 ETF", "ETF", "Index ETFs", ("index", "small_cap")),
    ("DIA", "SPDR Dow Jones ETF", "ETF", "Index ETFs", ("index", "dow")),
    ("AAPL", "Apple", "Technology", "Mega Cap Tech", ("consumer_tech", "liquid")),
    ("MSFT", "Microsoft", "Technology", "AI Cloud", ("ai_cloud", "mega_cap")),
    ("NVDA", "NVIDIA", "Technology", "AI Compute", ("ai_compute", "ai_semis")),
    ("TSLA", "Tesla", "Consumer Discretionary", "High Beta Growth", ("ev", "high_beta")),
    ("AMZN", "Amazon", "Consumer Discretionary", "AI Cloud", ("ai_cloud", "commerce")),
    ("META", "Meta Platforms", "Communication Services", "AI Cloud", ("ai_cloud", "ads")),
    ("GOOGL", "Alphabet", "Communication Services", "AI Cloud", ("ai_cloud", "search")),
    ("AMD", "Advanced Micro Devices", "Technology", "AI Compute", ("ai_compute", "ai_semis")),
    ("AVGO", "Broadcom", "Technology", "Semis / Foundry / Tools", ("ai_semis", "networking")),
    ("NFLX", "Netflix", "Communication Services", "Consumer Internet", ("streaming", "growth")),
    ("COST", "Costco", "Consumer Staples", "Defensive Growth", ("retail", "quality")),
    ("JPM", "JPMorgan Chase", "Financials", "Financials", ("bank", "quality")),
    ("BAC", "Bank of America", "Financials", "Financials", ("bank", "rate_sensitive")),
    ("WFC", "Wells Fargo", "Financials", "Financials", ("bank", "rate_sensitive")),
    ("GS", "Goldman Sachs", "Financials", "Financials", ("bank", "capital_markets")),
    ("MS", "Morgan Stanley", "Financials", "Financials", ("bank", "capital_markets")),
    ("XOM", "Exxon Mobil", "Energy", "Energy", ("oil", "large_cap")),
    ("CVX", "Chevron", "Energy", "Energy", ("oil", "large_cap")),
    ("COP", "ConocoPhillips", "Energy", "Energy", ("oil", "e_and_p")),
    ("UNH", "UnitedHealth", "Healthcare", "Healthcare", ("managed_care", "defensive")),
    ("LLY", "Eli Lilly", "Healthcare", "Healthcare", ("pharma", "growth")),
    ("MRK", "Merck", "Healthcare", "Healthcare", ("pharma", "defensive")),
    ("JNJ", "Johnson & Johnson", "Healthcare", "Healthcare", ("pharma", "defensive")),
    ("ABBV", "AbbVie", "Healthcare", "Healthcare", ("pharma", "income")),
    ("HD", "Home Depot", "Consumer Discretionary", "Industrials / Consumer", ("housing", "retail")),
    ("WMT", "Walmart", "Consumer Staples", "Defensive Growth", ("retail", "defensive")),
    ("MCD", "McDonald's", "Consumer Discretionary", "Industrials / Consumer", ("restaurant", "defensive")),
    ("NKE", "Nike", "Consumer Discretionary", "Industrials / Consumer", ("apparel", "consumer")),
    ("BA", "Boeing", "Industrials", "Industrials / Consumer", ("aerospace", "cyclical")),
    ("CAT", "Caterpillar", "Industrials", "Industrials / Consumer", ("machinery", "cyclical")),
    ("GE", "GE Aerospace", "Industrials", "Industrials / Consumer", ("aerospace", "quality")),
    ("DIS", "Disney", "Communication Services", "Consumer Internet", ("media", "turnaround")),
    ("T", "AT&T", "Communication Services", "Defensive Value", ("telecom", "income")),
    ("V", "Visa", "Financials", "Payments", ("payments", "quality")),
    ("MA", "Mastercard", "Financials", "Payments", ("payments", "quality")),
    ("CRM", "Salesforce", "Technology", "AI Software / Data", ("ai_software", "enterprise")),
    ("ORCL", "Oracle", "Technology", "AI Cloud", ("ai_cloud", "database")),
    ("ADBE", "Adobe", "Technology", "AI Software / Data", ("ai_software", "creative")),
    ("INTC", "Intel", "Technology", "Semis / Foundry / Tools", ("ai_semis", "turnaround")),
    ("MU", "Micron", "Technology", "Semis / Foundry / Tools", ("memory", "ai_semis")),
    ("QCOM", "Qualcomm", "Technology", "Semis / Foundry / Tools", ("mobile_semis", "ai_edge")),
    ("SMCI", "Super Micro Computer", "Technology", "AI Compute", ("ai_compute", "servers")),
    ("PLTR", "Palantir", "Technology", "AI Software / Data", ("ai_software", "data")),
    ("COIN", "Coinbase", "Financials", "Crypto / Fintech Beta", ("crypto_beta", "fintech")),
    ("SHOP", "Shopify", "Technology", "AI Software / Data", ("commerce", "growth")),
    ("UBER", "Uber", "Industrials", "AI Software / Data", ("mobility", "platform")),
    ("ARM", "Arm Holdings", "Technology", "AI Compute", ("ai_compute", "ai_semis")),
    ("MRVL", "Marvell", "Technology", "AI Semis", ("ai_semis", "networking")),
    ("TSM", "Taiwan Semiconductor", "Technology", "Semis / Foundry / Tools", ("foundry", "ai_semis")),
    ("ASML", "ASML", "Technology", "Semis / Foundry / Tools", ("lithography", "ai_semis")),
    ("ANET", "Arista Networks", "Technology", "AI Infra", ("ai_infra", "networking")),
    ("DELL", "Dell Technologies", "Technology", "AI Infra", ("ai_infra", "servers")),
    ("NOW", "ServiceNow", "Technology", "AI Software / Data", ("ai_software", "enterprise")),
    ("SNOW", "Snowflake", "Technology", "AI Software / Data", ("ai_software", "data")),
    ("DDOG", "Datadog", "Technology", "AI Infra", ("ai_infra", "observability")),
    ("MDB", "MongoDB", "Technology", "AI Software / Data", ("ai_software", "database")),
    ("CRWD", "CrowdStrike", "Technology", "AI Security", ("ai_security", "cybersecurity")),
    ("PANW", "Palo Alto Networks", "Technology", "AI Security", ("ai_security", "cybersecurity")),
    ("NET", "Cloudflare", "Technology", "AI Infra", ("ai_infra", "edge")),
    ("AI", "C3.ai", "Technology", "AI Software / Data", ("ai_software", "high_beta")),
    ("PATH", "UiPath", "Technology", "AI Software / Data", ("ai_software", "automation")),
    ("IBM", "IBM", "Technology", "AI Cloud", ("ai_cloud", "enterprise")),
    ("TXN", "Texas Instruments", "Technology", "Semis / Foundry / Tools", ("analog_semis", "quality")),
    ("AMAT", "Applied Materials", "Technology", "Semis / Foundry / Tools", ("semi_equipment", "ai_semis")),
    ("LRCX", "Lam Research", "Technology", "Semis / Foundry / Tools", ("semi_equipment", "ai_semis")),
    ("KLAC", "KLA", "Technology", "Semis / Foundry / Tools", ("semi_equipment", "ai_semis")),
    ("ADI", "Analog Devices", "Technology", "Semis / Foundry / Tools", ("analog_semis", "quality")),
    ("MSTR", "MicroStrategy", "Technology", "Crypto / Fintech Beta", ("crypto_beta", "high_beta")),
    ("HOOD", "Robinhood", "Financials", "Crypto / Fintech Beta", ("fintech", "high_beta")),
    ("PYPL", "PayPal", "Financials", "Payments", ("payments", "turnaround")),
    ("SQ", "Block", "Financials", "Crypto / Fintech Beta", ("fintech", "payments")),
    ("AXP", "American Express", "Financials", "Financials", ("payments", "consumer_credit")),
    ("BLK", "BlackRock", "Financials", "Financials", ("asset_manager", "quality")),
    ("SCHW", "Charles Schwab", "Financials", "Financials", ("brokerage", "rate_sensitive")),
    ("C", "Citigroup", "Financials", "Financials", ("bank", "value")),
    ("PFE", "Pfizer", "Healthcare", "Healthcare", ("pharma", "value")),
    ("TMO", "Thermo Fisher", "Healthcare", "Healthcare", ("life_science", "quality")),
    ("ISRG", "Intuitive Surgical", "Healthcare", "Healthcare", ("medtech", "growth")),
    ("ABT", "Abbott Laboratories", "Healthcare", "Healthcare", ("medtech", "defensive")),
    ("PEP", "PepsiCo", "Consumer Staples", "Defensive Growth", ("staples", "defensive")),
    ("KO", "Coca-Cola", "Consumer Staples", "Defensive Growth", ("staples", "defensive")),
    ("PG", "Procter & Gamble", "Consumer Staples", "Defensive Growth", ("staples", "defensive")),
    ("LOW", "Lowe's", "Consumer Discretionary", "Industrials / Consumer", ("housing", "retail")),
    ("SBUX", "Starbucks", "Consumer Discretionary", "Industrials / Consumer", ("restaurant", "consumer")),
    ("GM", "General Motors", "Consumer Discretionary", "High Beta Growth", ("autos", "cyclical")),
    ("F", "Ford", "Consumer Discretionary", "High Beta Growth", ("autos", "cyclical")),
    ("RIVN", "Rivian", "Consumer Discretionary", "High Beta Growth", ("ev", "high_beta")),
    ("LULU", "Lululemon", "Consumer Discretionary", "Industrials / Consumer", ("apparel", "growth")),
    ("XLE", "Energy Select Sector SPDR", "ETF", "Energy", ("sector_etf", "energy")),
    ("XLK", "Technology Select Sector SPDR", "ETF", "Index ETFs", ("sector_etf", "tech")),
    ("SMH", "VanEck Semiconductor ETF", "ETF", "AI Semis", ("sector_etf", "ai_semis")),
    ("SOXX", "iShares Semiconductor ETF", "ETF", "AI Semis", ("sector_etf", "ai_semis")),
    ("ARKK", "ARK Innovation ETF", "ETF", "High Beta Growth", ("growth", "high_beta")),
    ("TLT", "iShares 20+ Year Treasury ETF", "ETF", "Macro ETFs", ("rates", "macro")),
    ("GLD", "SPDR Gold Shares", "ETF", "Macro ETFs", ("gold", "macro")),
    ("USO", "United States Oil Fund", "ETF", "Energy", ("oil", "macro")),
    ("HYG", "iShares High Yield Bond ETF", "ETF", "Macro ETFs", ("credit", "macro")),
]


_ACTIVE_STOCK_ROWS = _RAW_STOCKS[:100]
DEFAULT_SYMBOLS = tuple(row[0] for row in _ACTIVE_STOCK_ROWS)
AI_SYMBOLS = (
    "NVDA",
    "AMD",
    "AVGO",
    "MSFT",
    "GOOGL",
    "META",
    "AMZN",
    "ORCL",
    "CRM",
    "ADBE",
    "PLTR",
    "SMCI",
    "MU",
    "QCOM",
    "INTC",
    "ARM",
    "MRVL",
    "TSM",
    "ASML",
    "ANET",
    "DELL",
    "NOW",
    "SNOW",
    "DDOG",
    "MDB",
    "CRWD",
    "PANW",
    "NET",
    "AI",
    "PATH",
)

_AI_FIVE_LAYER_ROWS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("CEG", "Constellation Energy", "Utilities", "Energy", ("ai_energy", "nuclear", "power")),
    ("VST", "Vistra", "Utilities", "Energy", ("ai_energy", "power", "merchant_power")),
    ("NRG", "NRG Energy", "Utilities", "Energy", ("ai_energy", "power")),
    ("NEE", "NextEra Energy", "Utilities", "Energy", ("ai_energy", "renewables", "utility")),
    ("SO", "Southern Company", "Utilities", "Energy", ("ai_energy", "utility")),
    ("DUK", "Duke Energy", "Utilities", "Energy", ("ai_energy", "utility")),
    ("GEV", "GE Vernova", "Industrials", "Energy", ("ai_energy", "grid", "power_equipment")),
    ("ETN", "Eaton", "Industrials", "Energy", ("ai_energy", "electrical", "power_management")),
    ("PWR", "Quanta Services", "Industrials", "Energy", ("ai_energy", "grid", "infrastructure")),
    ("VRT", "Vertiv", "Industrials", "Energy", ("ai_energy", "data_center_power", "cooling")),
    ("CARR", "Carrier Global", "Industrials", "Energy", ("ai_energy", "cooling", "data_center")),
    ("CCJ", "Cameco", "Energy", "Energy", ("ai_energy", "uranium", "nuclear")),
    ("NVDA", "NVIDIA", "Technology", "Chips", ("accelerator", "ai_factory", "networking")),
    ("AMD", "Advanced Micro Devices", "Technology", "Chips", ("accelerator", "gpu", "cpu")),
    ("AVGO", "Broadcom", "Technology", "Chips", ("custom_silicon", "networking", "ai_semis")),
    ("QCOM", "Qualcomm", "Technology", "Chips", ("edge_ai", "mobile_semis")),
    ("MRVL", "Marvell", "Technology", "Chips", ("networking", "custom_silicon")),
    ("ARM", "Arm Holdings", "Technology", "Chips", ("cpu_ip", "edge_ai")),
    ("INTC", "Intel", "Technology", "Chips", ("cpu", "foundry", "turnaround")),
    ("MU", "Micron", "Technology", "Chips", ("memory", "hbm")),
    ("TSM", "Taiwan Semiconductor", "Technology", "Chips", ("foundry", "advanced_node")),
    ("ASML", "ASML", "Technology", "Chips", ("lithography", "semi_equipment")),
    ("AMAT", "Applied Materials", "Technology", "Chips", ("semi_equipment", "wafer_tools")),
    ("LRCX", "Lam Research", "Technology", "Chips", ("semi_equipment", "etch")),
    ("KLAC", "KLA", "Technology", "Chips", ("semi_equipment", "inspection")),
    ("TXN", "Texas Instruments", "Technology", "Chips", ("analog_semis", "industrial")),
    ("ADI", "Analog Devices", "Technology", "Chips", ("analog_semis", "edge_ai")),
    ("MCHP", "Microchip Technology", "Technology", "Chips", ("microcontrollers", "edge_ai")),
    ("MPWR", "Monolithic Power Systems", "Technology", "Chips", ("power_semis", "data_center")),
    ("ON", "ON Semiconductor", "Technology", "Chips", ("power_semis", "edge_ai")),
    ("SMH", "VanEck Semiconductor ETF", "ETF", "Chips", ("sector_etf", "ai_semis")),
    ("SOXX", "iShares Semiconductor ETF", "ETF", "Chips", ("sector_etf", "ai_semis")),
    ("MSFT", "Microsoft", "Technology", "Infrastructure", ("cloud", "models", "enterprise_ai")),
    ("AMZN", "Amazon", "Consumer Discretionary", "Infrastructure", ("cloud", "ai_platform", "commerce")),
    ("GOOGL", "Alphabet", "Communication Services", "Infrastructure", ("cloud", "models", "search")),
    ("META", "Meta Platforms", "Communication Services", "Infrastructure", ("models", "ads", "open_models")),
    ("ORCL", "Oracle", "Technology", "Infrastructure", ("cloud", "database", "enterprise_ai")),
    ("IBM", "IBM", "Technology", "Infrastructure", ("enterprise_ai", "hybrid_cloud", "models")),
    ("ANET", "Arista Networks", "Technology", "Infrastructure", ("networking", "data_center")),
    ("CSCO", "Cisco", "Technology", "Infrastructure", ("networking", "security")),
    ("DELL", "Dell Technologies", "Technology", "Infrastructure", ("servers", "storage")),
    ("HPE", "Hewlett Packard Enterprise", "Technology", "Infrastructure", ("servers", "networking")),
    ("SMCI", "Super Micro Computer", "Technology", "Infrastructure", ("servers", "ai_factory")),
    ("EQIX", "Equinix", "Real Estate", "Infrastructure", ("data_center", "colo")),
    ("DLR", "Digital Realty", "Real Estate", "Infrastructure", ("data_center", "colo")),
    ("NET", "Cloudflare", "Technology", "Infrastructure", ("edge", "security", "inference")),
    ("DDOG", "Datadog", "Technology", "Infrastructure", ("observability", "cloud_ops")),
    ("PLTR", "Palantir", "Technology", "Models", ("model_ops", "enterprise_ai", "data")),
    ("SNOW", "Snowflake", "Technology", "Models", ("data_cloud", "model_data")),
    ("MDB", "MongoDB", "Technology", "Models", ("database", "developer_data")),
    ("AI", "C3.ai", "Technology", "Models", ("enterprise_ai", "high_beta")),
    ("CRM", "Salesforce", "Technology", "Applications", ("enterprise_apps", "agentic_crm")),
    ("NOW", "ServiceNow", "Technology", "Applications", ("workflow", "enterprise_apps")),
    ("ADBE", "Adobe", "Technology", "Applications", ("creative_ai", "enterprise_apps")),
    ("CRWD", "CrowdStrike", "Technology", "Applications", ("ai_security", "cybersecurity")),
    ("PANW", "Palo Alto Networks", "Technology", "Applications", ("ai_security", "cybersecurity")),
    ("PATH", "UiPath", "Technology", "Applications", ("automation", "agentic_workflows")),
    ("UBER", "Uber", "Industrials", "Applications", ("mobility_ai", "marketplace")),
    ("TSLA", "Tesla", "Consumer Discretionary", "Applications", ("robotics", "autonomy", "high_beta")),
    ("ISRG", "Intuitive Surgical", "Healthcare", "Applications", ("robotics", "medtech")),
    ("APP", "AppLovin", "Technology", "Applications", ("ai_ads", "high_beta")),
    ("DUOL", "Duolingo", "Communication Services", "Applications", ("consumer_ai", "education")),
    ("SHOP", "Shopify", "Technology", "Applications", ("commerce_ai", "merchant_tools")),
]


def liquidity_tier_for(tags: tuple[str, ...]) -> str:
    if "sector_etf" in tags or "mega_cap" in tags or "liquid" in tags:
        return "core"
    if "high_beta" in tags or "turnaround" in tags:
        return "high_beta"
    return "core"


def make_stock_meta(index: int, row: tuple[str, str, str, str, tuple[str, ...]]) -> StockMeta:
    symbol, name, sector, layer, tags = row
    return StockMeta(
        symbol=symbol,
        name=name,
        sector=sector,
        layer=layer,
        tags=tags,
        rank=index + 1,
        liquidity_tier=liquidity_tier_for(tags),
    )


_DEFAULT_META_BY_SYMBOL = {row[0]: make_stock_meta(index, row) for index, row in enumerate(_ACTIVE_STOCK_ROWS)}
_AI_FIVE_LAYER_META_BY_SYMBOL = {row[0]: make_stock_meta(index, row) for index, row in enumerate(_AI_FIVE_LAYER_ROWS)}
_META_BY_SYMBOL = {**_DEFAULT_META_BY_SYMBOL, **_AI_FIVE_LAYER_META_BY_SYMBOL}
AI_FIVE_LAYER_SYMBOLS = tuple(dict.fromkeys(row[0] for row in _AI_FIVE_LAYER_ROWS))


def stock_universe(universe: str = "default") -> list[StockMeta]:
    normalized = (universe or "default").lower()
    if normalized in {"ai_five_layer", "ai5", "ai-five-layer"}:
        symbols: Iterable[str] = AI_FIVE_LAYER_SYMBOLS
        meta_by_symbol = _AI_FIVE_LAYER_META_BY_SYMBOL
    elif normalized == "ai":
        symbols = AI_SYMBOLS
        meta_by_symbol = _META_BY_SYMBOL
    elif normalized == "all":
        symbols = tuple(_META_BY_SYMBOL)
        meta_by_symbol = _META_BY_SYMBOL
    else:
        symbols = DEFAULT_SYMBOLS
        meta_by_symbol = _DEFAULT_META_BY_SYMBOL
    return [meta_by_symbol[symbol] for symbol in symbols if symbol in meta_by_symbol]


def stock_universe_payload(universe: str = "default") -> dict[str, object]:
    stocks = stock_universe(universe)
    layers: dict[str, int] = {}
    for stock in stocks:
        layers[stock.layer] = layers.get(stock.layer, 0) + 1
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "universe": universe or "default",
        "count": len(stocks),
        "stocks": [stock.to_dict() for stock in stocks],
        "layers": [{"name": name, "count": count} for name, count in sorted(layers.items())],
        "layer_model": "ai_five_layer_cake" if (universe or "").lower() in {"ai_five_layer", "ai5", "ai-five-layer"} else "market_layers",
        "layer_order": ["Energy", "Chips", "Infrastructure", "Models", "Applications"],
        "btc_eth_removed_from_main_path": True,
        "options_are_secondary": True,
    }
