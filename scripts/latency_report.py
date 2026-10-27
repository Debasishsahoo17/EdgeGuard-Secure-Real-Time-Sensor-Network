"""Collect live observed MQTT ingestion latency/reliability through the EdgeGuard REST API.

Run while Docker Compose is active. The values are timestamps attached to each
reading by the gateway, not a synchronized physical-network latency guarantee.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time
from urllib.request import urlopen


def percentile(numbers: list[float], q: float) -> float:
    """Nearest rank percentile, well-defined for empty inputs."""
    if not numbers:
        return 0.0
    ordered = sorted(numbers)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def fetch_json(base: str, path: str):
    with urlopen(base.rstrip("/") + path, timeout=5) as response:
        return json.load(response)


def collect(base: str, seconds: float, poll: float) -> tuple[list[dict], list[dict]]:
    seen = set()
    readings = []
    snapshots = []
    start = time.monotonic()
    while True:
        try:
            batch = fetch_json(base, "/api/telemetry?limit=500")
            overview = fetch_json(base, "/api/overview")
            snapshots.append({"collected_at": time.time(), **overview})
            for item in batch:
                key = (item["node_id"], item["seq"])
                if key not in seen:
                    seen.add(key)
                    readings.append(item)
        except OSError as exc:
            raise RuntimeError(f"Cannot reach EdgeGuard at {base}: {exc}") from exc
        remaining = seconds - (time.monotonic() - start)
        if remaining <= 0:
            break
        time.sleep(min(remaining, poll))
    return readings, snapshots


def summarize(readings: list[dict], snapshots: list[dict]) -> dict:
    latencies = [max(0, float(i["latency_ms"])) for i in readings]
    first, last = snapshots[0], snapshots[-1]
    return {"measurements_seen": len(readings),
            "latency_avg_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            "latency_p50_ms": round(percentile(latencies, .50), 2),
            "latency_p95_ms": round(percentile(latencies, .95), 2),
            "latency_max_ms": round(max(latencies, default=0), 2),
            "retries_during_poll": max(0, last["retries"] - first["retries"]),
            "dropped_during_poll": max(0, last["dropped"] - first["dropped"]),
            "failures_during_poll": max(0, last["failed"] - first["failed"]),
            "duplicate_frames_during_poll": max(0, last["duplicates"] - first["duplicates"]),
            "active_nodes_at_end": last["nodes_online"]}


def main():
    parser = argparse.ArgumentParser(description="EdgeGuard observed latency benchmark")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--poll", type=float, default=2)
    parser.add_argument("--out", type=Path, default=Path("results/latency_report.csv"))
    args = parser.parse_args()
    if args.seconds < 0 or args.poll <= 0:
        parser.error("seconds cannot be negative and poll must be positive")
    readings, snapshots = collect(args.url, args.seconds, args.poll)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cols = ("node_id", "seq", "temperature", "humidity", "vibration", "battery",
            "generated_at", "received_at", "latency_ms", "attempts")
    with args.out.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=cols)
        writer.writeheader()
        for reading in sorted(readings, key=lambda r: r["received_at"]):
            writer.writerow({key: reading[key] for key in cols})
    summary = summarize(readings, snapshots)
    summary.update({"source":args.url, "sample_seconds":args.seconds,
                    "captured_at":datetime.now(timezone.utc).isoformat(),
                    "note":"gateway/sensor wall-clock difference, not synchronized one-way network latency"})
    json_path = args.out.with_suffix(".summary.json")
    json_path.write_text(json.dumps(summary, indent=2) + "\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print(f"Saved {args.out} and {json_path}")


if __name__ == "__main__":
    main()
