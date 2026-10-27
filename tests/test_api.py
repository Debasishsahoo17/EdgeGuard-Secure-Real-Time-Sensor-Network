from fastapi.testclient import TestClient
from edgeguard.api import create_app
from edgeguard.config import Settings


def test_dashboard_health_metrics_and_authorized_ack(tmp_path):
    s = Settings(database_path=str(tmp_path / "api.db"), dashboard_token="test-token", node_count=2)
    app = create_app(s, start_mqtt=False)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert "EdgeGuard" in c.get("/").text
        assert c.get("/api/health").json()["service"] == "edgeguard-gateway"
        assert c.get("/api/overview").json()["nodes_total"] == 2
        assert len(c.get("/api/nodes").json()) == 2
        assert len(c.get("/api/trends").json()["throughput"]) == 30
        assert c.get("/api/telemetry?limit=999999").status_code == 422
        app.state.store.add_alert("sensor-01", "security", "critical", "Test alert")
        assert c.post("/api/alerts/1/ack").status_code == 401
        assert c.post("/api/alerts/1/ack", headers={"Authorization":"Bearer wrong"}).status_code == 401
        assert c.post("/api/alerts/1/ack", headers={"Authorization":"Bearer test-token"}).status_code == 200
        assert c.post("/api/alerts/999/ack", headers={"Authorization":"Bearer test-token"}).status_code == 404
        assert c.get("/api/overview").json()["unacknowledged_alerts"] == 0
