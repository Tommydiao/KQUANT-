"""Independent quote evidence for reported positions; never submits an order."""


def fetch(position, main_db, *, option_loader=None, stock_loader=None):
    if option_loader is None:
        from .options_expression import option_contract_snapshot
        option_loader = option_contract_snapshot
    if stock_loader is None:
        from .stock_signals import api_stock_quotes_batch
        stock_loader = api_stock_quotes_batch
    result = {"option": {}, "underlying": {}, "errors": {}}
    try:
        result["option"] = option_loader(position["contract_id"], main_db)
    except Exception as exc:
        result["errors"]["option"] = type(exc).__name__
    try:
        response = stock_loader([position["symbol"]], db_path=main_db)
        result["underlying"] = next((row for row in response.get("items", [])
            if row.get("symbol") == position["symbol"] and row.get("provider_status") == "available"), {})
    except Exception as exc:
        result["errors"]["underlying"] = type(exc).__name__
    # Keep original field times, including cached times. Fetch completion is not
    # evidence that an old price has become fresh.
    return result
