from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m kquant.dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8001, type=int)
    parser.add_argument("--config", default="config/default.yml")
    args = parser.parse_args()
    # Windows Proactor accept can lose its listener on a disconnected health probe.
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run(create_app(args.config), host=args.host, port=args.port, loop=loop)


if __name__ == "__main__":
    main()
