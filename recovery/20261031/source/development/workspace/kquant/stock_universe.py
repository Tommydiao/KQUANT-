from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Literal


UniverseName = Literal["default", "ai", "ai_five_layer", "space_robotics", "physical_ai", "all"]


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
    ("MSTR", "MicroStrategy", "Technology", "Technology", ("high_beta",)),
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


_CORE_200_ADDITIONAL_ROWS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
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
    ("CSCO", "Cisco", "Technology", "Infrastructure", ("networking", "security")),
    ("HPE", "Hewlett Packard Enterprise", "Technology", "Infrastructure", ("servers", "networking")),
    ("EQIX", "Equinix", "Real Estate", "Infrastructure", ("data_center", "colo")),
    ("DLR", "Digital Realty", "Real Estate", "Infrastructure", ("data_center", "colo")),
    ("MCHP", "Microchip Technology", "Technology", "Chips", ("microcontrollers", "edge_ai")),
    ("MPWR", "Monolithic Power Systems", "Technology", "Chips", ("power_semis", "data_center")),
    ("ON", "ON Semiconductor", "Technology", "Chips", ("power_semis", "edge_ai")),
    ("APP", "AppLovin", "Technology", "Applications", ("ai_ads", "high_beta")),
    ("DUOL", "Duolingo", "Communication Services", "Applications", ("consumer_ai", "education")),
    ("KKR", "KKR", "Financials", "Financials", ("asset_manager", "private_markets")),
    ("BX", "Blackstone", "Financials", "Financials", ("asset_manager", "private_markets")),
    ("APO", "Apollo Global Management", "Financials", "Financials", ("asset_manager", "private_credit")),
    ("ICE", "Intercontinental Exchange", "Financials", "Financials", ("exchange", "market_data")),
    ("CME", "CME Group", "Financials", "Financials", ("exchange", "derivatives")),
    ("MSCI", "MSCI", "Financials", "Financials", ("index_provider", "market_data")),
    ("SPGI", "S&P Global", "Financials", "Financials", ("ratings", "market_data")),
    ("MCO", "Moody's", "Financials", "Financials", ("ratings", "analytics")),
    ("CB", "Chubb", "Financials", "Financials", ("insurance", "quality")),
    ("PGR", "Progressive", "Financials", "Financials", ("insurance", "quality")),
    ("TRV", "Travelers", "Financials", "Financials", ("insurance", "defensive")),
    ("AFL", "Aflac", "Financials", "Financials", ("insurance", "quality")),
    ("AMGN", "Amgen", "Healthcare", "Healthcare", ("biotech", "large_cap")),
    ("GILD", "Gilead Sciences", "Healthcare", "Healthcare", ("biotech", "value")),
    ("REGN", "Regeneron", "Healthcare", "Healthcare", ("biotech", "quality")),
    ("VRTX", "Vertex Pharmaceuticals", "Healthcare", "Healthcare", ("biotech", "quality")),
    ("DHR", "Danaher", "Healthcare", "Healthcare", ("life_science", "quality")),
    ("SYK", "Stryker", "Healthcare", "Healthcare", ("medtech", "quality")),
    ("BSX", "Boston Scientific", "Healthcare", "Healthcare", ("medtech", "growth")),
    ("MDT", "Medtronic", "Healthcare", "Healthcare", ("medtech", "value")),
    ("ELV", "Elevance Health", "Healthcare", "Healthcare", ("managed_care", "defensive")),
    ("CI", "Cigna", "Healthcare", "Healthcare", ("managed_care", "value")),
    ("CVS", "CVS Health", "Healthcare", "Healthcare", ("managed_care", "retail_health")),
    ("MELI", "MercadoLibre", "Consumer Discretionary", "Consumer Internet", ("commerce", "latin_america", "growth")),
    ("ABNB", "Airbnb", "Consumer Discretionary", "Consumer Internet", ("travel", "platform")),
    ("MAR", "Marriott International", "Consumer Discretionary", "Industrials / Consumer", ("travel", "quality")),
    ("BKNG", "Booking Holdings", "Consumer Discretionary", "Consumer Internet", ("travel", "platform")),
    ("DASH", "DoorDash", "Consumer Discretionary", "Consumer Internet", ("delivery", "platform")),
    ("CMG", "Chipotle Mexican Grill", "Consumer Discretionary", "Industrials / Consumer", ("restaurant", "growth")),
    ("ORLY", "O'Reilly Automotive", "Consumer Discretionary", "Industrials / Consumer", ("auto_parts", "quality")),
    ("AZO", "AutoZone", "Consumer Discretionary", "Industrials / Consumer", ("auto_parts", "quality")),
    ("ROST", "Ross Stores", "Consumer Discretionary", "Industrials / Consumer", ("retail", "value")),
    ("TJX", "TJX Companies", "Consumer Discretionary", "Industrials / Consumer", ("retail", "value")),
    ("RTX", "RTX", "Industrials", "Industrials / Consumer", ("defense", "aerospace")),
    ("LMT", "Lockheed Martin", "Industrials", "Industrials / Consumer", ("defense", "quality")),
    ("NOC", "Northrop Grumman", "Industrials", "Industrials / Consumer", ("defense", "quality")),
    ("GD", "General Dynamics", "Industrials", "Industrials / Consumer", ("defense", "quality")),
    ("HON", "Honeywell", "Industrials", "Industrials / Consumer", ("industrial_tech", "quality")),
    ("MMM", "3M", "Industrials", "Industrials / Consumer", ("industrial", "turnaround")),
    ("DE", "Deere", "Industrials", "Industrials / Consumer", ("machinery", "cyclical")),
    ("UPS", "UPS", "Industrials", "Industrials / Consumer", ("logistics", "cyclical")),
    ("FDX", "FedEx", "Industrials", "Industrials / Consumer", ("logistics", "cyclical")),
    ("WM", "Waste Management", "Industrials", "Industrials / Consumer", ("waste", "defensive")),
    ("LIN", "Linde", "Materials", "Industrials / Consumer", ("industrial_gases", "quality")),
    ("TEAM", "Atlassian", "Technology", "AI Software / Data", ("developer_tools", "ai_software")),
    ("WDAY", "Workday", "Technology", "AI Software / Data", ("enterprise_apps", "hr_software")),
    ("ZS", "Zscaler", "Technology", "AI Security", ("cybersecurity", "cloud_security")),
    ("OKTA", "Okta", "Technology", "AI Security", ("identity", "cybersecurity")),
    ("FTNT", "Fortinet", "Technology", "AI Security", ("cybersecurity", "network_security")),
    ("AKAM", "Akamai", "Technology", "AI Infra", ("edge", "security")),
    ("CDNS", "Cadence Design Systems", "Technology", "Semis / Foundry / Tools", ("eda", "semi_software")),
    ("SNPS", "Synopsys", "Technology", "Semis / Foundry / Tools", ("eda", "semi_software")),
    ("ADSK", "Autodesk", "Technology", "AI Software / Data", ("design_software", "enterprise")),
    ("INTU", "Intuit", "Technology", "AI Software / Data", ("software", "fintech")),
    ("XLF", "Financial Select Sector SPDR", "ETF", "Financials", ("sector_etf", "financials")),
    ("XLI", "Industrial Select Sector SPDR", "ETF", "Industrials / Consumer", ("sector_etf", "industrials")),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "ETF", "Industrials / Consumer", ("sector_etf", "consumer")),
    ("XLV", "Health Care Select Sector SPDR", "ETF", "Healthcare", ("sector_etf", "healthcare")),
    ("XLU", "Utilities Select Sector SPDR", "ETF", "Energy", ("sector_etf", "utilities")),
    ("XLP", "Consumer Staples Select Sector SPDR", "ETF", "Defensive Growth", ("sector_etf", "staples")),
    ("XLRE", "Real Estate Select Sector SPDR", "ETF", "Macro ETFs", ("sector_etf", "real_estate")),
    ("XLC", "Communication Services Select Sector SPDR", "ETF", "Consumer Internet", ("sector_etf", "communication")),
    ("XBI", "SPDR S&P Biotech ETF", "ETF", "Healthcare", ("sector_etf", "biotech")),
    ("IBB", "iShares Biotechnology ETF", "ETF", "Healthcare", ("sector_etf", "biotech")),
    ("KRE", "SPDR S&P Regional Banking ETF", "ETF", "Financials", ("sector_etf", "regional_banks")),
    ("XRT", "SPDR S&P Retail ETF", "ETF", "Industrials / Consumer", ("sector_etf", "retail")),
    ("FCX", "Freeport-McMoRan", "Materials", "Energy", ("copper", "materials")),
    ("NUE", "Nucor", "Materials", "Industrials / Consumer", ("steel", "cyclical")),
    ("STLD", "Steel Dynamics", "Materials", "Industrials / Consumer", ("steel", "cyclical")),
    ("CLF", "Cleveland-Cliffs", "Materials", "High Beta Growth", ("steel", "high_beta")),
    ("ALB", "Albemarle", "Materials", "High Beta Growth", ("lithium", "cyclical")),
    ("FSLR", "First Solar", "Technology", "Energy", ("solar", "energy_transition")),
    ("ENPH", "Enphase Energy", "Technology", "High Beta Growth", ("solar", "high_beta")),
    ("ROK", "Rockwell Automation", "Industrials", "Industrials / Consumer", ("automation", "industrial_tech")),
    ("TTD", "The Trade Desk", "Technology", "AI Software / Data", ("ai_ads", "software")),
    ("RDDT", "Reddit", "Communication Services", "Consumer Internet", ("social", "high_beta")),
    ("PINS", "Pinterest", "Communication Services", "Consumer Internet", ("social", "ads")),
    ("SE", "Sea Limited", "Communication Services", "Consumer Internet", ("gaming", "commerce", "international")),
    ("TGT", "Target", "Consumer Staples", "Defensive Growth", ("retail", "value")),
]

_SPACE_ROBOTICS_ROWS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("RKLB", "Rocket Lab", "Industrials", "Space / Robotics", ("space", "launch", "high_beta")),
    ("ASTS", "AST SpaceMobile", "Communication Services", "Space / Robotics", ("space", "satellite", "high_beta")),
    ("LUNR", "Intuitive Machines", "Industrials", "Space / Robotics", ("space", "lunar", "high_beta")),
    ("PL", "Planet Labs", "Industrials", "Space / Robotics", ("space", "satellite_imagery", "high_beta")),
    ("IRDM", "Iridium Communications", "Communication Services", "Space / Robotics", ("space", "satellite_network")),
    ("KTOS", "Kratos Defense & Security", "Industrials", "Space / Robotics", ("space", "defense_tech", "drones")),
    ("LHX", "L3Harris Technologies", "Industrials", "Space / Robotics", ("space", "defense", "communications")),
    ("LDOS", "Leidos", "Industrials", "Space / Robotics", ("defense_tech", "space_services")),
    ("TDY", "Teledyne Technologies", "Industrials", "Space / Robotics", ("sensors", "aerospace", "robotics")),
    ("HEI", "HEICO", "Industrials", "Space / Robotics", ("aerospace", "components", "quality")),
    ("ACHR", "Archer Aviation", "Industrials", "Space / Robotics", ("evtol", "aviation", "high_beta")),
    ("JOBY", "Joby Aviation", "Industrials", "Space / Robotics", ("evtol", "aviation", "high_beta")),
    ("SYM", "Symbotic", "Industrials", "Space / Robotics", ("warehouse_robotics", "automation", "high_beta")),
    ("SERV", "Serve Robotics", "Industrials", "Space / Robotics", ("delivery_robotics", "autonomy", "high_beta")),
    ("TER", "Teradyne", "Technology", "Space / Robotics", ("robotics", "test_equipment", "automation")),
    ("ZBRA", "Zebra Technologies", "Technology", "Space / Robotics", ("automation", "robotics", "supply_chain")),
    ("CGNX", "Cognex", "Technology", "Space / Robotics", ("machine_vision", "automation", "robotics")),
    ("AMBA", "Ambarella", "Technology", "Space / Robotics", ("edge_ai", "computer_vision", "autonomy", "high_beta")),
    ("ARBE", "Arbe Robotics", "Technology", "Space / Robotics", ("radar", "autonomy", "robotics", "high_beta")),
    ("OUST", "Ouster", "Technology", "Space / Robotics", ("lidar", "robotics", "high_beta")),
    ("MBLY", "Mobileye", "Technology", "Space / Robotics", ("autonomy", "robotics", "high_beta")),
    ("BOTZ", "Global X Robotics & AI ETF", "ETF", "Space / Robotics", ("robotics_etf", "automation")),
    ("ROBO", "ROBO Global Robotics ETF", "ETF", "Space / Robotics", ("robotics_etf", "automation")),
    ("ARKQ", "ARK Autonomous Technology ETF", "ETF", "Space / Robotics", ("autonomy_etf", "robotics")),
    ("ITA", "iShares U.S. Aerospace & Defense ETF", "ETF", "Space / Robotics", ("aerospace_etf", "defense")),
    ("XAR", "SPDR S&P Aerospace & Defense ETF", "ETF", "Space / Robotics", ("aerospace_etf", "defense")),
    ("UFO", "Procure Space ETF", "ETF", "Space / Robotics", ("space_etf", "satellite")),
]

_PHYSICAL_AI_ROWS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("ROK", "Rockwell Automation", "Industrials", "Embodied AI Components", ("industrial_automation", "robotics", "controls")),
    ("TER", "Teradyne", "Technology", "Embodied AI Components", ("robotics", "test_equipment", "automation")),
    ("SYM", "Symbotic", "Industrials", "Embodied AI Components", ("warehouse_robotics", "automation", "high_beta")),
    ("ISRG", "Intuitive Surgical", "Healthcare", "Embodied AI Components", ("surgical_robotics", "medtech", "robotics")),
    ("ZBRA", "Zebra Technologies", "Technology", "Embodied AI Components", ("automation", "robotics", "supply_chain")),
    ("CGNX", "Cognex", "Technology", "Embodied AI Components", ("machine_vision", "sensors", "robotics")),
    ("SERV", "Serve Robotics", "Industrials", "Embodied AI Components", ("delivery_robotics", "autonomy", "high_beta")),
    ("TRMB", "Trimble", "Technology", "Embodied AI Components", ("positioning", "sensors", "industrial_automation")),
    ("KEYS", "Keysight Technologies", "Technology", "Embodied AI Components", ("test_equipment", "sensors", "robotics")),
    ("ADI", "Analog Devices", "Technology", "Embodied AI Components", ("sensors", "analog_semis", "edge_ai")),
    ("ON", "ON Semiconductor", "Technology", "Embodied AI Components", ("sensors", "power_semis", "edge_ai")),
    ("MPWR", "Monolithic Power Systems", "Technology", "Embodied AI Components", ("motor_control", "power_semis", "robotics")),
    ("BOTZ", "Global X Robotics & AI ETF", "ETF", "Embodied AI Components", ("robotics_etf", "automation")),
    ("ROBO", "ROBO Global Robotics ETF", "ETF", "Embodied AI Components", ("robotics_etf", "automation")),
    ("AVAV", "AeroVironment", "Industrials", "Drones / Low Altitude", ("drones", "unmanned_systems", "defense", "high_beta")),
    ("KTOS", "Kratos Defense & Security", "Industrials", "Drones / Low Altitude", ("drones", "defense_tech", "unmanned_systems")),
    ("RCAT", "Red Cat Holdings", "Technology", "Drones / Low Altitude", ("drones", "defense_tech", "high_beta")),
    ("ONDS", "Ondas Holdings", "Technology", "Drones / Low Altitude", ("drones", "autonomous_systems", "high_beta")),
    ("UMAC", "Unusual Machines", "Technology", "Drones / Low Altitude", ("drones", "components", "high_beta")),
    ("EH", "EHang", "Industrials", "Drones / Low Altitude", ("evtol", "autonomous_aircraft", "high_beta")),
    ("ACHR", "Archer Aviation", "Industrials", "Drones / Low Altitude", ("evtol", "aviation", "high_beta")),
    ("JOBY", "Joby Aviation", "Industrials", "Drones / Low Altitude", ("evtol", "aviation", "high_beta")),
    ("TXT", "Textron", "Industrials", "Drones / Low Altitude", ("aerospace", "defense", "aircraft")),
    ("LHX", "L3Harris Technologies", "Industrials", "Drones / Low Altitude", ("defense", "communications", "drones")),
    ("LDOS", "Leidos", "Industrials", "Drones / Low Altitude", ("defense_tech", "mission_systems")),
    ("ITA", "iShares U.S. Aerospace & Defense ETF", "ETF", "Drones / Low Altitude", ("aerospace_etf", "defense")),
    ("XAR", "SPDR S&P Aerospace & Defense ETF", "ETF", "Drones / Low Altitude", ("aerospace_etf", "defense")),
    ("AAPL", "Apple", "Technology", "Spatial Computing", ("spatial_computing", "mixed_reality", "consumer_tech")),
    ("META", "Meta Platforms", "Communication Services", "Spatial Computing", ("spatial_computing", "vr_ar", "ai_platform")),
    ("SNAP", "Snap", "Communication Services", "Spatial Computing", ("ar", "consumer_camera", "high_beta")),
    ("VUZI", "Vuzix", "Technology", "Spatial Computing", ("ar_glasses", "spatial_computing", "high_beta")),
    ("KOPN", "Kopin", "Technology", "Spatial Computing", ("microdisplays", "ar_vr", "high_beta")),
    ("MVIS", "MicroVision", "Technology", "Spatial Computing", ("lidar", "3d_sensing", "high_beta")),
    ("LAZR", "Luminar", "Technology", "Spatial Computing", ("lidar", "autonomy", "high_beta")),
    ("OUST", "Ouster", "Technology", "Spatial Computing", ("lidar", "3d_sensing", "robotics", "high_beta")),
    ("HSAI", "Hesai Group", "Technology", "Spatial Computing", ("lidar", "3d_sensing", "adr", "high_beta")),
    ("AEVA", "Aeva Technologies", "Technology", "Spatial Computing", ("lidar", "4d_sensing", "high_beta")),
    ("MBLY", "Mobileye", "Technology", "Spatial Computing", ("autonomy", "vision", "robotics", "high_beta")),
    ("AMBA", "Ambarella", "Technology", "Spatial Computing", ("edge_ai", "computer_vision", "autonomy", "high_beta")),
    ("COHR", "Coherent", "Technology", "Spatial Computing", ("optical", "photonics", "3d_sensing")),
    ("LITE", "Lumentum", "Technology", "Spatial Computing", ("optical", "photonics", "3d_sensing", "high_beta")),
    ("RKLB", "Rocket Lab", "Industrials", "Space Exploration", ("space", "launch", "spacecraft", "high_beta")),
    ("ASTS", "AST SpaceMobile", "Communication Services", "Space Exploration", ("space", "satellite", "direct_to_device", "high_beta")),
    ("LUNR", "Intuitive Machines", "Industrials", "Space Exploration", ("space", "lunar", "high_beta")),
    ("PL", "Planet Labs", "Industrials", "Space Exploration", ("space", "satellite_imagery", "high_beta")),
    ("IRDM", "Iridium Communications", "Communication Services", "Space Exploration", ("space", "satellite_network")),
    ("SPIR", "Spire Global", "Industrials", "Space Exploration", ("space", "satellite_data", "high_beta")),
    ("BKSY", "BlackSky Technology", "Industrials", "Space Exploration", ("space", "satellite_imagery", "high_beta")),
    ("RDW", "Redwire", "Industrials", "Space Exploration", ("space", "space_infrastructure", "high_beta")),
    ("GSAT", "Globalstar", "Communication Services", "Space Exploration", ("space", "satellite_network", "high_beta")),
    ("SATL", "Satellogic", "Industrials", "Space Exploration", ("space", "earth_observation", "high_beta")),
    ("BA", "Boeing", "Industrials", "Space Exploration", ("space", "aerospace", "defense")),
    ("LMT", "Lockheed Martin", "Industrials", "Space Exploration", ("space", "defense", "aerospace")),
    ("NOC", "Northrop Grumman", "Industrials", "Space Exploration", ("space", "defense", "aerospace")),
    ("RTX", "RTX", "Industrials", "Space Exploration", ("space", "defense", "aerospace")),
    ("GD", "General Dynamics", "Industrials", "Space Exploration", ("space", "defense", "aerospace")),
    ("KTOS", "Kratos Defense & Security", "Industrials", "Space Exploration", ("space", "defense_tech", "satellite")),
    ("UFO", "Procure Space ETF", "ETF", "Space Exploration", ("space_etf", "satellite")),
    ("ARKX", "ARK Space Exploration ETF", "ETF", "Space Exploration", ("space_etf", "innovation")),
]


_ACTIVE_STOCK_ROWS = _RAW_STOCKS[:100] + _CORE_200_ADDITIONAL_ROWS
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
    ("NVTS", "Navitas Semiconductor", "Technology", "Chips", ("power_semis", "gan", "sic", "ai_power", "high_beta")),
    ("SNDK", "SanDisk", "Technology", "Chips", ("storage", "nand", "ai_storage", "high_beta")),
    ("WDC", "Western Digital", "Technology", "Chips", ("storage", "hdd", "nand", "ai_storage")),
    ("STX", "Seagate Technology", "Technology", "Chips", ("storage", "hdd", "ai_storage")),
    ("AMBA", "Ambarella", "Technology", "Chips", ("edge_ai", "computer_vision", "autonomy", "high_beta")),
    ("ACLS", "Axcelis Technologies", "Technology", "Chips", ("semi_equipment", "power_semis", "high_beta")),
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
    ("COHR", "Coherent", "Technology", "Infrastructure", ("optical", "photonics", "datacenter_interconnect", "ai_networking")),
    ("LITE", "Lumentum", "Technology", "Infrastructure", ("optical", "photonics", "datacenter_interconnect", "high_beta")),
    ("FN", "Fabrinet", "Technology", "Infrastructure", ("optical", "datacenter_interconnect", "manufacturing")),
    ("ALAB", "Astera Labs", "Technology", "Infrastructure", ("connectivity", "pcie", "ai_datacenter", "high_beta")),
    ("CRDO", "Credo Technology", "Technology", "Infrastructure", ("connectivity", "serdes", "ai_networking", "high_beta")),
    ("CLS", "Celestica", "Technology", "Infrastructure", ("ai_servers", "electronics_manufacturing", "high_beta")),
    ("JBL", "Jabil", "Technology", "Infrastructure", ("ai_servers", "electronics_manufacturing")),
    ("FLEX", "Flex", "Technology", "Infrastructure", ("ai_servers", "electronics_manufacturing")),
    ("IREN", "IREN", "Technology", "Infrastructure", ("neocloud", "gpu_cloud", "ai_datacenter", "power", "high_beta")),
    ("NBIS", "Nebius Group", "Technology", "Infrastructure", ("neocloud", "gpu_cloud", "ai_datacenter", "high_beta")),
    ("CORZ", "Core Scientific", "Technology", "Infrastructure", ("neocloud", "ai_datacenter", "bitcoin_miner_conversion", "high_beta")),
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
_SPACE_ROBOTICS_META_BY_SYMBOL = {row[0]: make_stock_meta(index, row) for index, row in enumerate(_SPACE_ROBOTICS_ROWS)}
_PHYSICAL_AI_META_BY_SYMBOL = {row[0]: make_stock_meta(index, row) for index, row in enumerate(_PHYSICAL_AI_ROWS)}
_META_BY_SYMBOL = {
    **_DEFAULT_META_BY_SYMBOL,
    **_AI_FIVE_LAYER_META_BY_SYMBOL,
    **_SPACE_ROBOTICS_META_BY_SYMBOL,
    **_PHYSICAL_AI_META_BY_SYMBOL,
}
AI_FIVE_LAYER_SYMBOLS = tuple(dict.fromkeys(row[0] for row in _AI_FIVE_LAYER_ROWS))
SPACE_ROBOTICS_SYMBOLS = tuple(dict.fromkeys(row[0] for row in _SPACE_ROBOTICS_ROWS))
PHYSICAL_AI_SYMBOLS = tuple(dict.fromkeys(row[0] for row in _PHYSICAL_AI_ROWS))


def stock_universe(universe: str = "default") -> list[StockMeta]:
    normalized = (universe or "default").lower()
    if normalized in {"ai_five_layer", "ai5", "ai-five-layer"}:
        symbols: Iterable[str] = AI_FIVE_LAYER_SYMBOLS
        meta_by_symbol = _AI_FIVE_LAYER_META_BY_SYMBOL
    elif normalized in {"space_robotics", "space-robotics", "space"}:
        symbols = SPACE_ROBOTICS_SYMBOLS
        meta_by_symbol = _SPACE_ROBOTICS_META_BY_SYMBOL
    elif normalized in {"physical_ai", "physical-ai", "physical"}:
        symbols = PHYSICAL_AI_SYMBOLS
        meta_by_symbol = _PHYSICAL_AI_META_BY_SYMBOL
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
    normalized = (universe or "default").lower()
    layers: dict[str, int] = {}
    for stock in stocks:
        layers[stock.layer] = layers.get(stock.layer, 0) + 1
    if normalized == "default":
        display_name = "Core 200"
    elif normalized in {"ai_five_layer", "ai5", "ai-five-layer"}:
        display_name = "AI Five-Layer"
    elif normalized in {"space_robotics", "space-robotics", "space"}:
        display_name = "Space / Robotics"
    elif normalized in {"physical_ai", "physical-ai", "physical"}:
        display_name = "Physical AI"
    elif normalized == "ai":
        display_name = "AI Watchlist"
    else:
        display_name = "All"
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "universe": universe or "default",
        "display_name": display_name,
        "count": len(stocks),
        "stocks": [stock.to_dict() for stock in stocks],
        "layers": [{"name": name, "count": count} for name, count in sorted(layers.items())],
        "layer_model": "ai_five_layer_cake" if normalized in {"ai_five_layer", "ai5", "ai-five-layer"} else "market_layers",
        "layer_order": [
            "Energy",
            "Chips",
            "Infrastructure",
            "Models",
            "Applications",
            "Embodied AI Components",
            "Drones / Low Altitude",
            "Spatial Computing",
            "Space Exploration",
            "Space / Robotics",
        ],
    }
