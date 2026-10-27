import json
import time
from edgeguard.config import Settings
from edgeguard.gateway import EdgeGateway
from edgeguard.security import sign
from edgeguard.store import Store


def make_packet(s, seq=1, node="sensor-01", **overrides):
    now = time.time()
    item = {"kind":"telemetry", "node_id":node, "seq":seq, "attempt":1,
            "generated_at":now-.015, "sent_at":now,
            "temperature":26.2,"humidity":52,"vibration":2.3,"battery":88.2, **overrides}
    return json.dumps(sign(item,s.master_key,node)).encode()


def setup_gateway(**options):
    s = Settings(node_count=2, ack_loss=0, **options)
    db = Store(":memory:")
    published = []
    gateway = EdgeGateway(s, db, lambda topic, body: published.append((topic, json.loads(body))))
    return s, db, gateway, published


def test_ingestion_and_authenticated_ack():
    s, db, gw, published = setup_gateway()
    assert gw.handle_packet("edgeguard/telemetry/sensor-01", make_packet(s)) == "accepted"
    assert db.overview(["sensor-01", "sensor-02"], 20)["messages"] == 1
    assert len(published) == 1
    assert published[0][0] == "edgeguard/acks/sensor-01"
    from edgeguard.security import verify
    assert verify(published[0][1], s.master_key, "sensor-01")
    db.close()


def test_duplicate_is_idempotent_but_reacked():
    s, db, gw, published = setup_gateway()
    pkt = make_packet(s)
    assert gw.handle_packet("edgeguard/telemetry/sensor-01", pkt) == "accepted"
    assert gw.handle_packet("edgeguard/telemetry/sensor-01", pkt) == "duplicate"
    assert len(published) == 2
    assert db.overview(["sensor-01", "sensor-02"], 20)["messages"] == 1
    assert db.counters()["duplicates"] == 1
    db.close()


def test_reject_tamper_mismatch_and_oversized_packet():
    s, db, gw, published = setup_gateway()
    pkt = json.loads(make_packet(s))
    pkt["temperature"] = 80
    assert gw.handle_packet("edgeguard/telemetry/sensor-01", json.dumps(pkt).encode()) == "rejected"
    assert gw.handle_packet("edgeguard/telemetry/sensor-02", make_packet(s)) == "rejected"
    assert gw.handle_packet("edgeguard/telemetry/sensor-01", b"X" * 4097) == "rejected"
    assert gw.handle_packet("edgeguard/bad/sensor-01", b"{}") == "rejected"
    assert db.counters()["rejected"] == 4
    assert not published
    assert any(a["kind"] == "security" for a in db.alerts())
    db.close()


def test_alert_thresholds_and_cooldown():
    s, db, gw, published = setup_gateway()
    for seq in (1, 2):
        assert gw.handle_packet("edgeguard/telemetry/sensor-01",
                                make_packet(s, seq=seq, temperature=39.2, vibration=8.0, battery=14)) == "accepted"
    kinds = [a["kind"] for a in db.alerts()]
    assert sorted(kinds) == ["battery", "temperature", "vibration"]
    db.close()


def test_health_update_and_metrics():
    s, db, gw, published = setup_gateway()
    item = {"kind":"health", "node_id":"sensor-01", "sent_at":time.time(),
            "attempts":10, "dropped":3, "retries":4, "failed":1, "acked":8, "rtt_ms":42.2}
    payload = json.dumps(sign(item, s.master_key, "sensor-01")).encode()
    assert gw.handle_packet("edgeguard/health/sensor-01", payload) == "health"
    assert db.overview(["sensor-01", "sensor-02"], 20)["retries"] == 4
    item["acked"] = 99
    payload = json.dumps(sign(item, s.master_key, "sensor-01")).encode()
    assert gw.handle_packet("edgeguard/health/sensor-01", payload) == "rejected"
    db.close()


def test_persistent_deduplication(tmp_path):
    p = str(tmp_path / "db.sqlite")
    s = Settings(node_count=1,ack_loss=0)
    pkt = make_packet(s)
    first = Store(p)
    assert EdgeGateway(s,first).handle_packet("edgeguard/telemetry/sensor-01",pkt) == "accepted"
    first.close()
    second = Store(p)
    assert EdgeGateway(s,second).handle_packet("edgeguard/telemetry/sensor-01",pkt) == "duplicate"
    assert len(second.telemetry()) == 1
    second.close()
