from __future__ import annotations

import base64
import binascii
import hashlib
import io
from typing import Any


MAX_IMAGE_BYTES = 8 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


def decode_journal_image(image_base64: str, content_type: str) -> bytes:
    normalized_type = str(content_type or "").lower()
    if normalized_type not in SUPPORTED_CONTENT_TYPES:
        raise ValueError("unsupported journal image type")
    try:
        payload = base64.b64decode(str(image_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 journal image") from exc
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("journal image is empty or exceeds 8 MB")
    signatures = {
        "image/png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": payload.startswith(b"\xff\xd8\xff"),
        "image/webp": payload.startswith(b"RIFF") and payload[8:12] == b"WEBP",
    }
    if not signatures[normalized_type]:
        raise ValueError("journal image signature does not match content type")
    return payload


def extract_roll_journal_image_text(image_bytes: bytes) -> dict[str, Any]:
    """Run optional local OCR without sending a journal screenshot to a cloud service."""
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return {"status": "ocr_unavailable", "text": "", "image_sha256": image_hash, "engine": None}
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            text = str(pytesseract.image_to_string(image, lang="eng+chi_sim") or "").strip()
    except Exception as exc:
        return {
            "status": "ocr_failed",
            "text": "",
            "image_sha256": image_hash,
            "engine": "pytesseract",
            "reason": type(exc).__name__,
        }
    return {
        "status": "ocr_complete" if text else "ocr_empty",
        "text": text,
        "image_sha256": image_hash,
        "engine": "pytesseract",
    }


__all__ = ["MAX_IMAGE_BYTES", "SUPPORTED_CONTENT_TYPES", "decode_journal_image", "extract_roll_journal_image_text"]
