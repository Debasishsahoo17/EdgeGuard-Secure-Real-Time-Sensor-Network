"""Environment-only configuration, safe to load in a container or locally."""
from dataclasses import dataclass
import os


def env_float(name: str, default: float, low: float = 0.0, high: float = 1.0) -> float:
    value = float(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_gateway_user: str = os.getenv("MQTT_GATEWAY_USER", "gateway")
    mqtt_gateway_password: str = os.getenv("MQTT_GATEWAY_PASSWORD", "edgeguard-demo-gateway")
    mqtt_sensor_password: str = os.getenv("MQTT_SENSOR_PASSWORD", "edgeguard-demo-sensors")
    mqtt_tls_ca: str = os.getenv("MQTT_TLS_CA", "")
    master_key: str = os.getenv("EDGEGUARD_MASTER_KEY", "edgeguard-DEMO-master-key-change-before-deploying-2026")
    database_path: str = os.getenv("DATABASE_PATH", "data/edgeguard.db")
    dashboard_token: str = os.getenv("DASHBOARD_API_TOKEN", "demo-token-change-me")
    node_count: int = int(os.getenv("NODE_COUNT", "6"))
    interval: float = float(os.getenv("SENSOR_INTERVAL", "2.0"))
    packet_loss: float = env_float("PACKET_LOSS_RATE", 0.12)
    ack_loss: float = env_float("ACK_DROP_RATE", 0.16)
    retry_timeout: float = float(os.getenv("RETRY_TIMEOUT", "1.5"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    alert_cooldown: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "30"))
    stale_seconds: int = int(os.getenv("STALE_SECONDS", "20"))

    def __post_init__(self):
        if not 1 <= self.node_count <= 30:
            raise ValueError("NODE_COUNT must be between 1 and 30")
        if self.interval <= 0 or self.retry_timeout <= 0 or self.max_retries < 0:
            raise ValueError("Interval and timeout must be positive; retries cannot be negative")
        if len(self.master_key.encode()) < 32:
            raise ValueError("EDGEGUARD_MASTER_KEY must be at least 32 bytes")


def node_ids(settings: Settings) -> list[str]:
    return [f"sensor-{i:02d}" for i in range(1, settings.node_count + 1)]
