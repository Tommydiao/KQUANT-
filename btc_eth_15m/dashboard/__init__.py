__all__ = ["create_app"]


def __getattr__(name):
    if name == "create_app":
        from btc_eth_15m.dashboard.app import create_app

        return create_app
    raise AttributeError(name)
