"""Independent MQTT sensor clients with lossy links and application-level retries."""
import json
import logging
import random
import signal
import threading
import time
from .config import Settings, node_ids
from .security import decode, sign, verify

log = logging.getLogger(__name__)


class SensorNode:
    def __init__(self, node_id: str, settings: Settings, stop: threading.Event | None = None,
                 rng: random.Random | None = None):
        self.node_id = node_id
        self.settings = settings
        self.stop_event = stop or threading.Event()
        self.rng = rng or random.Random()
        self.client = None
        self.connected = threading.Event()
        self.ack_event = threading.Event()
        self.pending_seq = 0
        self.seq = int(time.time() * 1000)
        self.attempts = self.dropped = self.retries = self.failed = self.acked = 0
        self.rtt_ms = 0.0
        self.battery = 96.0 - int(node_id[-2:]) * 2
        self.started = time.monotonic()

    def _signed(self, kind: str, **fields) -> bytes:
        data = {"kind": kind, "node_id": self.node_id, "sent_at": time.time(), **fields}
        return json.dumps(sign(data, self.settings.master_key, self.node_id), separators=(",", ":")).encode()

    def on_ack(self, payload: bytes) -> bool:
        try:
            item = decode(payload)
            if (item.get("kind") != "ack" or item.get("status") != "stored" or
                    type(item.get("seq")) is not int or item["seq"] != self.pending_seq or
                    not verify(item, self.settings.master_key, self.node_id)):
                return False
            self.ack_event.set()
            return True
        except (ValueError, TypeError, KeyError):
            return False

    def reading(self) -> dict:
        index = int(self.node_id[-2:])
        tick = self.seq
        # One intentionally warm node + periodic outliers keep alerts demonstrable.
        heat = (6.6 if index == 3 else 0) + (6.0 if tick % 23 == 0 else 0)
        temp = 24.5 + index * .73 + heat + self.rng.uniform(-1.3, 1.3)
        vibration = 2.1 + self.rng.uniform(0, 2.1) + (5.6 if tick % 31 == 0 else 0)
        self.battery = max(8.0, self.battery - 0.015)
        return {"temperature": round(temp, 2), "humidity": round(45 + index * 2 + self.rng.uniform(-5, 5), 2),
                "vibration": round(vibration, 2), "battery": round(self.battery, 2)}

    def publish_health(self):
        if self.client and self.connected.is_set():
            payload = self._signed("health", attempts=self.attempts, dropped=self.dropped,
                                   retries=self.retries, failed=self.failed, acked=self.acked,
                                   rtt_ms=round(self.rtt_ms, 2))
            self.client.publish(f"edgeguard/health/{self.node_id}", payload, qos=1)

    def send_one(self) -> bool:
        """Retry the same seq until an authenticated application ACK or bounded failure."""
        self.seq += 1
        self.attempts += 1
        self.pending_seq = self.seq
        self.ack_event.clear()
        created = time.time()
        reading = self.reading()
        started = time.monotonic()
        for attempt in range(1, self.settings.max_retries + 2):
            if self.stop_event.is_set():
                return False
            if attempt > 1:
                self.retries += 1
            # Drop a *transmission*, not the MQTT message after broker PUBACK.
            if self.rng.random() < self.settings.packet_loss:
                self.dropped += 1
                log.debug("Simulated data loss: %s seq=%d attempt=%d", self.node_id, self.seq, attempt)
            elif self.client is not None and self.connected.is_set():
                data = self._signed("telemetry", seq=self.seq, attempt=attempt,
                                    generated_at=created, **reading)
                self.client.publish(f"edgeguard/telemetry/{self.node_id}", data, qos=1)
            if self.ack_event.wait(timeout=self.settings.retry_timeout):
                self.acked += 1
                sample_rtt = (time.monotonic() - started) * 1000
                self.rtt_ms = sample_rtt if self.acked == 1 else .7 * self.rtt_ms + .3 * sample_rtt
                return True
        self.failed += 1
        log.warning("Delivery timed out: %s seq %d after %d attempts", self.node_id, self.seq,
                    self.settings.max_retries + 1)
        return False

    def run(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("Install requirements.txt to use MQTT transport") from exc
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"edgeguard-{self.node_id}", protocol=mqtt.MQTTv311)
        client.username_pw_set(self.node_id, self.settings.mqtt_sensor_password)
        if self.settings.mqtt_tls_ca:
            client.tls_set(ca_certs=self.settings.mqtt_tls_ca)
        client.reconnect_delay_set(min_delay=1, max_delay=15)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code == 0:
                self.connected.set()
                c.subscribe(f"edgeguard/acks/{self.node_id}", qos=1)
                log.info("%s connected", self.node_id)
            else:
                self.connected.clear()
                log.error("%s connect refused: %s", self.node_id, reason_code)

        def on_disconnect(c, userdata, disconnect_flags, reason_code, properties):
            self.connected.clear()

        def on_message(c, userdata, message):
            if message.topic == f"edgeguard/acks/{self.node_id}":
                self.on_ack(message.payload)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        self.client = client
        client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, 60)
        client.loop_start()
        try:
            while not self.stop_event.is_set():
                if self.connected.wait(timeout=.5):
                    self.send_one()
                    self.publish_health()
                    self.stop_event.wait(self.settings.interval)
        finally:
            client.disconnect()
            client.loop_stop()
            self.client = None


def simulate(settings: Settings):
    stop = threading.Event()
    nodes = [SensorNode(node_id, settings, stop) for node_id in node_ids(settings)]
    threads = [threading.Thread(target=node.run, name=node.node_id, daemon=True) for node in nodes]

    def shutdown(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    for thread in threads:
        thread.start()
    log.info("Started %d sensor agents (packet-loss=%.0f%%)", len(nodes), settings.packet_loss * 100)
    while not stop.wait(1):
        pass
    for thread in threads:
        thread.join(timeout=5)
