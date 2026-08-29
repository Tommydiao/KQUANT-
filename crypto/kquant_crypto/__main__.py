from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .config import load_settings
from .db.migrations import migrate
from .security import generate_session_secret, hash_password


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

        settings = load_settings()
        uvicorn.run("kquant_crypto.dashboard.app:app", host=settings.host, port=settings.port, reload=False)
        return 0
    if args.command == "db":
        settings = load_settings()
        print(migrate(settings.db_path))
        return 0
    if args.command == "auth":
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
        from .staging import staging_status, verify_staging

        settings = load_settings()
        if args.action == "status":
            print(staging_status(settings))
        else:
            print(verify_staging(settings, apply_migrations=args.action == "migrate"))
        return 0
    if args.command == "gateway":
        import uvicorn

        uvicorn.run(
            "kquant_crypto.gateway:app",
            host="127.0.0.1",
            port=int(__import__("os").environ.get("KQUANT_GATEWAY_PORT", "8020")),
            reload=False,
        )
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
