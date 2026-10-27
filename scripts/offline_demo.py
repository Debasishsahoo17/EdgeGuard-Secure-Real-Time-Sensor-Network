"""Broker-free smoke demonstration of signed ingestion, idempotency, and alerts."""
import json
import time
from edgeguard.config import Settings
from edgeguard.gateway import EdgeGateway
from edgeguard.security import sign
from edgeguard.store import Store


def main():
    config = Settings(node_count=3, ack_loss=0)
    store = Store(":memory:")
    acknowledgements = []
    gateway = EdgeGateway(config, store, lambda t, p: acknowledgements.append((t, json.loads(p))))
    for i in range(1, 4):
        node_id = f"sensor-{i:02d}"
        for seq in range(1, 21):
            now = time.time()
            telemetry = {"kind":"telemetry", "node_id":node_id, "seq":seq, "attempt":1,
                         "generated_at":now-.015, "sent_at":now,
                         "temperature":39.0 if i == 3 else 25.0, "humidity":51.0,
                         "vibration":8.0 if seq % 10 == 0 else 2.5, "battery":85.0}
            payload = json.dumps(sign(telemetry,config.master_key,node_id)).encode()
            assert gateway.handle_packet(f"edgeguard/telemetry/{node_id}",payload) == "accepted"
            if seq == 1:
                assert gateway.handle_packet(f"edgeguard/telemetry/{node_id}",payload) == "duplicate"
    assert len(acknowledgements) == 63
    stats = store.overview([f"sensor-{i:02d}" for i in range(1,4)],30)
    assert stats["messages"] == 60 and stats["duplicates"] == 3
    print("OFFLINE DEMO PASSED — 60 authenticated readings, 3 de-duplicated retries,")
    print(f"{len(acknowledgements)} signed ACKs, {stats['unacknowledged_alerts']} anomaly alerts")
    print(json.dumps(stats,indent=2))
    store.close()


if __name__ == "__main__":
    main()
