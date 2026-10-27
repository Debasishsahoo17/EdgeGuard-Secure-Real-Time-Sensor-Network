import json
import time
import pytest
from edgeguard.security import sign, verify, decode, derived_key

MASTER = "test-master-key-very-long-and-private-0123456789"


def frame(node="sensor-01"):
    return {"kind": "telemetry", "node_id": node, "sent_at": time.time(), "seq": 1}


def test_valid_hmac_and_node_isolation():
    payload = sign(frame(), MASTER, "sensor-01")
    assert verify(payload, MASTER, "sensor-01")
    assert not verify(payload, MASTER, "sensor-02")
    assert derived_key(MASTER, "sensor-01") != derived_key(MASTER, "sensor-02")


def test_reject_tampering_and_bad_signature():
    original = sign(frame(), MASTER, "sensor-01")
    tampered = {**original, "seq": 90}
    assert not verify(tampered, MASTER, "sensor-01")
    assert not verify({**original, "mac": "a" * 64}, MASTER, "sensor-01")
    assert not verify({**original, "mac": None}, MASTER, "sensor-01")


def test_freshness_and_clock_skew():
    data = frame()
    data["sent_at"] -= 121
    assert not verify(sign(data, MASTER, "sensor-01"), MASTER, "sensor-01")
    data["sent_at"] += 242
    assert not verify(sign(data, MASTER, "sensor-01"), MASTER, "sensor-01")


def test_decode_rejects_bad_payloads():
    with pytest.raises(ValueError):
        decode(b"[1,2,3]")
    with pytest.raises(ValueError):
        decode(b"x" * 4097)
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        decode(b"not-json")


def test_cannot_sign_twice_or_bad_node():
    signed = sign(frame(), MASTER, "sensor-01")
    with pytest.raises(ValueError):
        sign(signed, MASTER, "sensor-01")
    with pytest.raises(ValueError):
        derived_key(MASTER, "../unsafe")
