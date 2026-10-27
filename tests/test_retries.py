import json
import random
import threading
from edgeguard.config import Settings
from edgeguard.gateway import EdgeGateway
from edgeguard.simulator import SensorNode
from edgeguard.store import Store


class SequenceRNG:
    def __init__(self, values):
        self.values = iter(values)
    def random(self):
        return next(self.values)
    def uniform(self, minimum, maximum):
        return (minimum + maximum) / 2


class DirectTransport:
    """Zero-network mock transport exercising real packet verification and ACK handling."""
    def __init__(self, gateway):
        self.gateway = gateway
    def publish(self, topic, payload, qos):
        return self.gateway.handle_packet(topic, payload)


def test_retry_after_simulated_data_loss():
    s = Settings(node_count=1, packet_loss=.5, ack_loss=0, retry_timeout=.002, max_retries=3)
    store = Store(":memory:")
    node = SensorNode("sensor-01", s, rng=SequenceRNG([0, .9]))
    gateway = EdgeGateway(s, store, publish=lambda t,p: node.on_ack(p))
    node.client = DirectTransport(gateway)
    node.connected.set()
    assert node.send_one()
    assert node.attempts == 1 and node.acked == 1
    assert node.retries == 1 and node.dropped == 1
    assert len(store.telemetry()) == 1
    store.close()


def test_duplicate_from_lost_ack_is_still_acknowledged():
    s = Settings(node_count=1, packet_loss=0, ack_loss=.5, retry_timeout=.002, max_retries=2)
    store = Store(":memory:")
    node = SensorNode("sensor-01", s, rng=SequenceRNG([1, 1]))
    ack_losses = iter([0, 1])
    gateway = EdgeGateway(s, store, publish=lambda t,p: node.on_ack(p),random_fn=lambda: next(ack_losses))
    node.client = DirectTransport(gateway)
    node.connected.set()
    assert node.send_one()
    assert node.retries == 1
    assert len(store.telemetry()) == 1
    assert store.counters()["duplicates"] == 1
    assert store.counters()["ack_dropped"] == 1
    store.close()


def test_exhausted_retry_budget_is_reported():
    s = Settings(node_count=1,packet_loss=1,ack_loss=0,retry_timeout=.001,max_retries=2)
    node = SensorNode("sensor-01", s, rng=random.Random(5))
    assert not node.send_one()
    assert node.dropped == 3 and node.retries == 2 and node.failed == 1


def test_forged_ack_does_not_satisfy_delivery():
    s = Settings(node_count=1)
    node = SensorNode("sensor-01", s)
    node.pending_seq = 100
    assert not node.on_ack(json.dumps({"kind":"ack","node_id":"sensor-01","seq":100,
                                      "sent_at":0,"status":"stored","mac":"0"*64}).encode())
    assert not node.ack_event.is_set()
