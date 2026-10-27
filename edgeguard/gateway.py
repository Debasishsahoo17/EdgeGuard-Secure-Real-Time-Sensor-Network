"""MQTT edge receiver: verify, persist, de-duplicate, alert, and acknowledge."""
import json
import logging
import random
import threading
import time
from typing import Callable
from .config import Settings, node_ids
from .security import decode, sign, verify
from .store import Store

log = logging.getLogger(__name__)


class EdgeGateway:
    def __init__(self, settings: Settings, store: Store,
                 publish: Callable[[str, bytes], None] | None = None,
                 random_fn: Callable[[], float] = random.random):
        self.settings = settings
        self.store = store
        self.publish = publish
        self.random_fn = random_fn
        self.client = None
        self.connected = threading.Event()
        self.allowed = set(node_ids(settings))

    def _reject(self, reason: str, node_id: str = "gateway") -> None:
        self.store.inc("rejected")
        self.store.add_alert(node_id, "security", "critical", f"Rejected packet: {reason}", self.settings.alert_cooldown)
        log.warning("Rejected packet from %s: %s", node_id, reason)

    def handle_packet(self, topic: str, payload: bytes, received_at: float | None = None) -> str:
        """Process an MQTT delivery; returns accepted/duplicate/health/rejected."""
        received_at = time.time() if received_at is None else received_at
        pieces = topic.split("/")
        if len(pieces) != 3 or pieces[0] != "edgeguard" or pieces[1] not in ("telemetry", "health"):
            self._reject("unexpected topic")
            return "rejected"
        channel, node_id = pieces[1], pieces[2]
        if node_id not in self.allowed:
            self._reject("unknown node", node_id)
            return "rejected"
        try:
            body = decode(payload)
            if not verify(body, self.settings.master_key, node_id, now=received_at):
                raise ValueError("invalid MAC, identity, or timestamp")
            if body.get("kind") != channel:
                raise ValueError("topic/kind mismatch")
            if channel == "telemetry":
                return self._telemetry(node_id, body, received_at)
            return self._health(node_id, body)
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            self._reject(str(exc), node_id)
            return "rejected"

    @staticmethod
    def _number(item: dict, name: str, minimum: float, maximum: float) -> float:
        val = item[name]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not minimum <= val <= maximum:
            raise ValueError(f"Invalid {name}")
        return float(val)

    def _telemetry(self, node_id: str, body: dict, received_at: float) -> str:
        seq = body["seq"]
        attempt = body["attempt"]
        if (type(seq) is not int or not 1 <= seq <= 2**53 or
                type(attempt) is not int or not 1 <= attempt <= self.settings.max_retries + 1):
            raise ValueError("Invalid sequence or attempt")
        for key, low, high in (("temperature", -40, 125), ("humidity", 0, 100),
                               ("vibration", 0, 100), ("battery", 0, 100)):
            self._number(body, key, low, high)
        generated = self._number(body, "generated_at", received_at - 120, received_at + 120)
        if generated > body["sent_at"] + 5:
            raise ValueError("Generated timestamp after transmission")
        is_new = self.store.save_reading(body, received_at)
        if is_new:
            self._check_thresholds(node_id, body)
        else:
            self.store.inc("duplicates")
        # Application ACK is authenticated and idempotent; even duplicate frames get ACKed.
        ack = sign({"kind": "ack", "node_id": node_id, "seq": seq,
                    "status": "stored", "sent_at": time.time()},
                   self.settings.master_key, node_id)
        if self.random_fn() < self.settings.ack_loss:
            self.store.inc("ack_dropped")
        elif self.publish is not None:
            try:
                self.publish(f"edgeguard/acks/{node_id}", json.dumps(ack).encode())
            except Exception:
                log.exception("Could not publish ACK for %s seq %s", node_id, seq)
        return "accepted" if is_new else "duplicate"

    def _health(self, node_id: str, body: dict) -> str:
        for name in ("attempts", "dropped", "retries", "failed", "acked"):
            value = body[name]
            if type(value) is not int or not 0 <= value <= 10**9:
                raise ValueError(f"Invalid {name}")
        if body["acked"] + body["failed"] > body["attempts"]:
            raise ValueError("Inconsistent health counters")
        self._number(body, "rtt_ms", 0, 120000)
        self.store.save_health(body)
        return "health"

    def _check_thresholds(self, node_id: str, body: dict) -> None:
        checks = [
            (body["temperature"] >= 36, "temperature", "warning", f"Temperature {body['temperature']:.1f}°C exceeds 36°C"),
            (body["vibration"] >= 7.0, "vibration", "critical", f"Vibration {body['vibration']:.1f} mm/s exceeds 7 mm/s"),
            (body["battery"] <= 20, "battery", "warning", f"Battery at {body['battery']:.0f}%"),
        ]
        for active, kind, severity, message in checks:
            if active:
                self.store.add_alert(node_id, kind, severity, message, self.settings.alert_cooldown)

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("Install requirements.txt to use MQTT transport") from exc
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edgeguard-gateway", protocol=mqtt.MQTTv311)
        client.username_pw_set(self.settings.mqtt_gateway_user, self.settings.mqtt_gateway_password)
        if self.settings.mqtt_tls_ca:
            client.tls_set(ca_certs=self.settings.mqtt_tls_ca)
        client.reconnect_delay_set(min_delay=1, max_delay=15)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code == 0:
                self.connected.set()
                c.subscribe([("edgeguard/telemetry/+", 1), ("edgeguard/health/+", 1)])
                log.info("Gateway connected to broker")
            else:
                self.connected.clear()
                log.error("Gateway connection refused: %s", reason_code)

        def on_disconnect(c, userdata, disconnect_flags, reason_code, properties):
            self.connected.clear()
            log.warning("Gateway disconnected: %s", reason_code)

        def on_message(c, userdata, message):
            try:
                self.handle_packet(message.topic, message.payload)
            except Exception:
                log.exception("Unexpected gateway processing failure")

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        self.client = client
        self.publish = lambda topic, payload: client.publish(topic, payload, qos=1)
        client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, 60)
        client.loop_start()

    def stop(self):
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
        self.connected.clear()
