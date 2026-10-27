"""Thread-safe SQLite persistence and dashboard aggregation."""
import math
import os
import sqlite3
import statistics
import threading
import time
from collections import defaultdict


def iso(ts: float | None) -> str | None:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts is not None else None


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=20)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL, seq INTEGER NOT NULL,
                temperature REAL NOT NULL, humidity REAL NOT NULL,
                vibration REAL NOT NULL, battery REAL NOT NULL,
                generated_at REAL NOT NULL, received_at REAL NOT NULL,
                latency_ms REAL NOT NULL, attempts INTEGER NOT NULL,
                UNIQUE(node_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_telemetry_recent ON telemetry(received_at DESC);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL,
                kind TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
                created_at REAL NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_kind ON alerts(node_id,kind,created_at DESC);
            CREATE TABLE IF NOT EXISTS node_stats (
                node_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL,
                dropped INTEGER NOT NULL, retries INTEGER NOT NULL,
                failed INTEGER NOT NULL, acked INTEGER NOT NULL,
                rtt_ms REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
            """)
            self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def inc(self, key: str):
        with self.lock, self.db:
            self.db.execute("INSERT INTO counters(key,value) VALUES (?,1) ON CONFLICT(key) DO UPDATE SET value=value+1", (key,))

    def save_reading(self, item: dict, received_at: float) -> bool:
        with self.lock, self.db:
            cursor = self.db.execute("""INSERT OR IGNORE INTO telemetry
                (node_id,seq,temperature,humidity,vibration,battery,generated_at,received_at,latency_ms,attempts)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (item["node_id"], item["seq"], item["temperature"], item["humidity"],
                 item["vibration"], item["battery"], item["generated_at"], received_at,
                 max(0, (received_at - item["generated_at"]) * 1000), item["attempt"]))
            return cursor.rowcount == 1

    def save_health(self, item: dict):
        with self.lock, self.db:
            self.db.execute("""INSERT INTO node_stats
                (node_id, attempts, dropped, retries, failed, acked, rtt_ms, updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET
                attempts=excluded.attempts, dropped=excluded.dropped,
                retries=excluded.retries, failed=excluded.failed,
                acked=excluded.acked, rtt_ms=excluded.rtt_ms, updated_at=excluded.updated_at""",
                (item["node_id"], item["attempts"], item["dropped"], item["retries"],
                 item["failed"], item["acked"], item["rtt_ms"], time.time()))

    def add_alert(self, node_id: str, kind: str, severity: str, message: str,
                  cooldown: int = 30, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.lock, self.db:
            latest = self.db.execute("SELECT created_at FROM alerts WHERE node_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
                                     (node_id, kind)).fetchone()
            if latest and now - latest[0] < cooldown:
                return False
            self.db.execute("INSERT INTO alerts(node_id,kind,severity,message,created_at) VALUES(?,?,?,?,?)",
                            (node_id, kind, severity, message, now))
            return True

    def acknowledge(self, alert_id: int) -> bool:
        with self.lock, self.db:
            return self.db.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,)).rowcount > 0

    def counters(self) -> dict:
        with self.lock:
            return {r["key"]: r["value"] for r in self.db.execute("SELECT key,value FROM counters")}

    def telemetry(self, limit: int = 60) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM telemetry ORDER BY received_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def alerts(self, limit: int = 40) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def nodes(self, names: list[str], stale_seconds: int) -> list[dict]:
        now = time.time()
        with self.lock:
            last = {r["node_id"]: dict(r) for r in self.db.execute("""
                SELECT t.* FROM telemetry t JOIN
                (SELECT node_id, MAX(id) AS latest_id FROM telemetry GROUP BY node_id) x
                ON t.id=x.latest_id""")}
            stats = {r["node_id"]: dict(r) for r in self.db.execute("SELECT * FROM node_stats")}
        result = []
        for name in names:
            item, stat = last.get(name), stats.get(name, {})
            age = round(now - item["received_at"], 1) if item else None
            result.append({
                "id": name, "status": "offline" if age is None or age > stale_seconds else "online",
                "last_seen": iso(item["received_at"]) if item else None,
                "age_seconds": age,
                "temperature": item["temperature"] if item else None,
                "humidity": item["humidity"] if item else None,
                "vibration": item["vibration"] if item else None,
                "battery": item["battery"] if item else None,
                "latency_ms": round(item["latency_ms"], 2) if item else None,
                "seq": item["seq"] if item else None,
                "attempts": stat.get("attempts", 0), "dropped": stat.get("dropped", 0),
                "retries": stat.get("retries", 0), "failed": stat.get("failed", 0),
                "acked": stat.get("acked", 0), "rtt_ms": round(stat.get("rtt_ms", 0), 2)
            })
        return result

    def overview(self, names: list[str], stale_seconds: int) -> dict:
        nodes = self.nodes(names, stale_seconds)
        with self.lock:
            count = self.db.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
            latencies = [r[0] for r in self.db.execute("SELECT latency_ms FROM telemetry ORDER BY id DESC LIMIT 500")]
            unacked = self.db.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged=0").fetchone()[0]
            recent = self.db.execute("SELECT COUNT(*) FROM telemetry WHERE received_at>=?", (time.time() - 60,)).fetchone()[0]
        s = self.counters()
        ordered = sorted(latencies)
        p95 = ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else 0
        stats = {k: sum(n[k] for n in nodes) for k in ("attempts", "dropped", "retries", "failed", "acked")}
        return {"nodes_total": len(nodes), "nodes_online": sum(n["status"] == "online" for n in nodes),
                "messages": count, "throughput_per_minute": recent,
                "latency_avg_ms": round(statistics.mean(latencies), 1) if latencies else 0,
                "latency_p95_ms": round(p95, 1), "unacknowledged_alerts": unacked,
                "duplicates": s.get("duplicates", 0), "rejected": s.get("rejected", 0),
                "ack_dropped": s.get("ack_dropped", 0), **stats}

    def trends(self, points: int = 30, window_seconds: int = 300) -> dict:
        now = time.time()
        bucket_size = window_seconds / points
        start = now - window_seconds
        with self.lock:
            rows = self.db.execute("SELECT received_at,latency_ms FROM telemetry WHERE received_at>=? ORDER BY received_at", (start,)).fetchall()
        bins: list[list[float]] = [[] for _ in range(points)]
        for row in rows:
            index = min(points - 1, max(0, int((row["received_at"] - start) / bucket_size)))
            bins[index].append(row["latency_ms"])
        return {"timestamps": [round(start + (i + 1) * bucket_size) for i in range(points)],
                "throughput": [len(b) for b in bins],
                "latency_ms": [round(statistics.mean(b), 1) if b else 0 for b in bins]}
