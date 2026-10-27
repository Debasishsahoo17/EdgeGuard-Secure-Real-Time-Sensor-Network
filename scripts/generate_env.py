"""Generate a private .env with random, demo-environment credentials."""
from pathlib import Path
from secrets import token_urlsafe

root = Path(__file__).resolve().parent.parent
file = root / ".env"
if file.exists():
    raise SystemExit("Refusing to overwrite existing .env. Back it up/remove it first.")
file.write_text("\n".join([
    "# Private demo credentials. Never commit this file.",
    f"MQTT_GATEWAY_PASSWORD={token_urlsafe(36)}",
    f"MQTT_SENSOR_PASSWORD={token_urlsafe(36)}",
    f"EDGEGUARD_MASTER_KEY={token_urlsafe(48)}",
    f"DASHBOARD_API_TOKEN={token_urlsafe(36)}",
    "NODE_COUNT=6", "SENSOR_INTERVAL=2.0", "PACKET_LOSS_RATE=0.12",
    "ACK_DROP_RATE=0.16", "MAX_RETRIES=3", "RETRY_TIMEOUT=1.5",
]) + "\n", encoding="utf-8")
file.chmod(0o600)
print(f"Generated {file}. Dashboard acknowledgement token is DASHBOARD_API_TOKEN in .env")
