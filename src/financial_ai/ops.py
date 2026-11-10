"""Local container health and explicitly synthetic end-to-end smoke check."""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path


def worker_health():
    heartbeat = Path(os.environ.get("WORKER_HEARTBEAT_PATH", "/tmp/worker-heartbeat"))
    if not heartbeat.exists() or time.time() - heartbeat.stat().st_mtime > 650:
        raise RuntimeError("Worker has no recent successful queue iteration")


def smoke(base="http://web:8080"):
    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload else None
        req = urllib.request.Request(
            base + path,
            data=data,
            headers={"Content-Type": "application/json", "Host": "localhost:8080"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    run = request("/api/v1/research-runs", {"ticker": "AAPL"})
    for _ in range(60):
        state = request(f"/api/v1/research-runs/{run['id']}")
        if state["status"] == "completed":
            snapshots = request(f"/api/v1/research-runs/{run['id']}/snapshot")
            lanes = {s["lane"]: s for s in snapshots}
            assert lanes["quote"]["payload"]["synthetic"] is True
            assert len(lanes["ohlcv"]["payload"]["candles"]) == 60
            assert lanes["charts"]["payload"]["charts"]
            report = request(f"/api/v1/research-runs/{run['id']}/reports/latest")
            assert (
                report["research_mode"] == "synthetic"
                and report["sections"]
                and report["evidence_links"]
            )
            print(
                "PASS: OFFLINE DEMO completed collection, analysis, chart and saved report through the shared pipeline."
            )
            return
        if state["status"] in {"failed", "cancelled"}:
            raise RuntimeError("Demo run did not complete; inspect compose logs")
        time.sleep(1)
    raise TimeoutError("Demo run did not finish within 60 seconds")


if __name__ == "__main__":
    if sys.argv[1:] == ["worker-health"]:
        worker_health()
    elif sys.argv[1:] == ["smoke"]:
        smoke()
    else:
        raise SystemExit("Use worker-health or smoke")
