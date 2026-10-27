"""Read-only monitoring APIs plus token-protected alert acknowledgement."""
from contextlib import asynccontextmanager
from pathlib import Path
import hmac
import time
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings, node_ids
from .gateway import EdgeGateway
from .store import Store

WEB = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None, start_mqtt: bool = True) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.database_path)
    gateway = EdgeGateway(settings, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_mqtt:
            gateway.start()
        yield
        gateway.stop()
        store.close()

    app = FastAPI(title="EdgeGuard API", version="1.0.0", lifespan=lifespan,
                  description="Secure real-time sensor gateway telemetry and diagnostics")
    app.state.store = store
    app.state.gateway = gateway
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(WEB / "index.html")

    @app.get("/api/health")
    def health():
        return {"service": "edgeguard-gateway", "gateway_connected": gateway.connected.is_set(),
                "time": time.time(), "database": "ok"}

    @app.get("/api/overview")
    def overview():
        return {**store.overview(node_ids(settings), settings.stale_seconds),
                "gateway_connected": gateway.connected.is_set()}

    @app.get("/api/nodes")
    def nodes():
        return store.nodes(node_ids(settings), settings.stale_seconds)

    @app.get("/api/telemetry")
    def telemetry(limit: int = Query(default=60, ge=1, le=500)):
        return store.telemetry(limit)

    @app.get("/api/alerts")
    def alerts(limit: int = Query(default=30, ge=1, le=200)):
        return store.alerts(limit)

    @app.get("/api/trends")
    def trends():
        return store.trends()

    @app.get("/api/config")
    def config():
        return {"node_count": settings.node_count, "stale_seconds": settings.stale_seconds,
                "packet_loss_rate": settings.packet_loss, "ack_drop_rate": settings.ack_loss,
                "max_retries": settings.max_retries, "sensor_interval": settings.interval}

    @app.post("/api/alerts/{alert_id}/ack")
    def acknowledge(alert_id: int, authorization: str | None = Header(default=None)):
        provided = (authorization or "").removeprefix("Bearer ")
        if not provided or not hmac.compare_digest(provided, settings.dashboard_token):
            raise HTTPException(401, detail="Valid dashboard token required")
        if not store.acknowledge(alert_id):
            raise HTTPException(404, detail="Alert not found")
        return {"acknowledged": True, "id": alert_id}

    return app


app = create_app()
