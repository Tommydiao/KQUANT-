from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def main() -> int:
    vapid = Vapid()
    vapid.generate_keys()
    private_value = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_value = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print("KQUANT_CRYPTO_WEB_PUSH_PUBLIC_KEY=" + b64url(public_value))
    print("KQUANT_CRYPTO_WEB_PUSH_PRIVATE_KEY=" + b64url(private_value))
    print("KQUANT_CRYPTO_WEB_PUSH_SUBJECT=mailto:replace-with-your-email@example.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
