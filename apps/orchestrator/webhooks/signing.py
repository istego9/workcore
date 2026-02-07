from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, Optional

HEADER_SIGNATURE = "X-Webhook-Signature"
HEADER_TIMESTAMP = "X-Webhook-Timestamp"


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    payload = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(
    secret: str,
    headers: Dict[str, str],
    body: bytes,
    tolerance_s: int = 300,
) -> bool:
    headers_lower = {k.lower(): v for k, v in headers.items()}
    signature = headers_lower.get(HEADER_SIGNATURE.lower())
    timestamp = headers_lower.get(HEADER_TIMESTAMP.lower())

    if signature:
        parts = dict(item.split("=") for item in signature.split(",") if "=" in item)
        ts = parts.get("t")
        sig = parts.get("v1")
    else:
        ts = timestamp
        sig = None

    if not ts or not sig:
        return False

    try:
        ts_val = int(ts)
    except ValueError:
        return False

    if abs(int(time.time()) - ts_val) > tolerance_s:
        return False

    expected = sign_payload(secret, ts, body)
    expected_sig = dict(item.split("=") for item in expected.split(",") if "=" in item).get("v1")
    if not expected_sig:
        return False

    return hmac.compare_digest(sig, expected_sig)
