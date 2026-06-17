from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Literal


UniverseName = Literal["default", "ai", "all"]


@dataclass(frozen=True)
class StockMeta:
    symbol: str
    name: str
    sector: str
    layer: str
    tags: tuple[str, ...]
    rank: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
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

_META_BY_SYMBOL = {
    symbol: StockMeta(symbol=symbol, name=name, sector=sector, layer=layer, tags=tags, rank=index + 1)
    for index, (symbol, name, sector, layer, tags) in enumerate(_ACTIVE_STOCK_ROWS)
}


def stock_universe(universe: str = "default") -> list[StockMeta]:
    normalized = (universe or "default").lower()
    if normalized == "ai":
        symbols: Iterable[str] = AI_SYMBOLS
    elif normalized == "all":
        symbols = tuple(_META_BY_SYMBOL)
    else:
        symbols = DEFAULT_SYMBOLS
    return [_META_BY_SYMBOL[symbol] for symbol in symbols if symbol in _META_BY_SYMBOL]


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
        "btc_eth_removed_from_main_path": True,
        "options_are_secondary": True,
    }
