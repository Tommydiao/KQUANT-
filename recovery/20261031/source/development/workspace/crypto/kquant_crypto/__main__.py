from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kquant-crypto")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve")
    db = sub.add_parser("db")
    db.add_argument("action", choices=["migrate"])
    auth = sub.add_parser("auth")
    auth.add_argument("action", choices=["hash-password", "generate-session-secret"])
    research = sub.add_parser("research")
    research.add_argument("action", choices=["versions"])
    staging = sub.add_parser("staging")
    staging.add_argument("action", choices=["status", "verify", "migrate"])
    sub.add_parser("gateway")
    args = parser.parse_args(argv)

    if args.command in {None, "serve"}:
        import uvicorn
        from .config import load_settings

        settings = load_settings()
        uvicorn.run("kquant_crypto.dashboard.app:app", host=settings.host, port=settings.port, reload=False)
        return 0
    if args.command == "db":
        from .config import load_settings
        from .db.migrations import migrate

        settings = load_settings()
        print(migrate(settings.db_path))
        return 0
    if args.command == "auth":
        from .security import generate_session_secret, hash_password

        if args.action == "generate-session-secret":
            print(generate_session_secret())
            return 0
        print(hash_password(getpass.getpass("Password: ")))
        return 0
    if args.command == "research":
        print("crypto_roll_v1.0.0")
        print("crypto_bayesian_v1.0.0")
        print("crypto_monte_carlo_v1.0.0")
        print("research_only=true")
        return 0
    if args.command == "staging":
        from .config import load_settings
        from .staging import staging_status, verify_staging

        settings = load_settings()
        if args.action == "status":
            print(staging_status(settings))
        else:
            print(verify_staging(settings, apply_migrations=args.action == "migrate"))
        return 0
    if args.command == "gateway":
        import uvicorn
        import os
        import ipaddress
        import socket
        lan = os.environ.get("KQUANT_GATEWAY_LAN_ADDRESS", "")
        if lan:
            from .gateway import WorkspaceSecurity
            security = WorkspaceSecurity.from_environment()
            address = ipaddress.ip_address(lan)
            if not security.enabled or not security.configured or address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
                raise ValueError("PRIVATE_LAN_AND_CONFIGURED_LOGIN_REQUIRED")
            sockets = []
            try:
                for host in ("127.0.0.1", lan):
                    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sockets.append(listener)
                    listener.bind((host, int(os.environ.get("KQUANT_GATEWAY_PORT", "8020"))))
                    listener.listen(128)
                server = uvicorn.Server(uvicorn.Config("kquant_crypto.gateway:app", reload=False))
                server.run(sockets=sockets)
            finally:
                for listener in sockets:
                    listener.close()
            return 0

        uvicorn.run(
            "kquant_crypto.gateway:app",
            host="127.0.0.1",
            port=int(__import__("os").environ.get("KQUANT_GATEWAY_PORT", "8020")),
            reload=False,
            loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto",
        )
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
