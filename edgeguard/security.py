"""Per-node, domain-separated HMAC authentication over canonical JSON."""
import hashlib
import hmac
import json
import re
import time
from typing import Any

NODE_ID = re.compile(r"^sensor-[0-9]{2}$")
MAX_BODY_BYTES = 4096


def derived_key(master: str, node_id: str) -> bytes:
    if not NODE_ID.fullmatch(node_id):
        raise ValueError("Invalid node identifier")
    return hmac.new(master.encode(), ("edgeguard:v1:" + node_id).encode(), hashlib.sha256).digest()


def canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sign(document: dict[str, Any], master: str, node_id: str) -> dict[str, Any]:
    if "mac" in document:
        raise ValueError("Payload already contains a signature")
    result = dict(document)
    result["mac"] = hmac.new(derived_key(master, node_id), canonical(result), hashlib.sha256).hexdigest()
    return result


def verify(document: Any, master: str, node_id: str, now: float | None = None,
           window: float = 120.0) -> bool:
    if not isinstance(document, dict) or document.get("node_id") != node_id:
        return False
    signature = document.get("mac")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    try:
        sent_at = document["sent_at"]
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            return False
        if abs((time.time() if now is None else now) - sent_at) > window:
            return False
        raw = {k: v for k, v in document.items() if k != "mac"}
        expected = hmac.new(derived_key(master, node_id), canonical(raw), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def decode(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BODY_BYTES:
        raise ValueError("Payload too large")
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object")
    return obj
