"""SQLite-backed device outbox. Remove telemetry only after an exact server acknowledgement."""

import argparse
import json
import os
import random
import signal
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import DEMO_DEVICE, DEMO_TOKEN
from .schemas import Reading
from .simulator import simulated_reading


class Outbox:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def enqueue(self, reading):
        reading = Reading.model_validate(reading)
        payload = json.dumps(reading.model_dump(mode="json"), sort_keys=True)
        event_id = str(reading.event_id)
        with self.connect() as db:
            existing = db.execute(
                "SELECT payload FROM outbox WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing and existing[0] != payload:
                raise ValueError("Event ID collision in the local outbox")
            db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?)", (event_id, payload))

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def drain(self, url, token, client=None):
        with self.connect() as db:
            pending = db.execute(
                "SELECT event_id,payload FROM outbox ORDER BY rowid LIMIT 100"
            ).fetchall()
        if not pending:
            return 0
        own_client = client is None
        client = client or httpx.Client(timeout=15)
        try:
            response = client.post(
                url.rstrip("/") + "/api/readings/batch",
                json={"readings": [json.loads(row[1]) for row in pending]},
                headers={"X-Device-Token": token},
            )
            response.raise_for_status()
            ack = response.json()
            expected = {row[0] for row in pending}
            if set(ack.get("event_ids", [])) != expected or (
                ack.get("accepted", 0) + ack.get("duplicates", 0) != len(pending)
            ):
                raise ValueError("Server acknowledgement does not cover the submitted batch")
            with self.connect() as db:
                db.executemany("DELETE FROM outbox WHERE event_id=? AND payload=?", pending)
            return len(pending)
        finally:
            if own_client:
                client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("GRIDSENSE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--device", default=os.getenv("DEVICE_ID", DEMO_DEVICE))
    parser.add_argument("--outbox", default="data/runtime/edge.db")
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Collect without attempting upload")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("interval must be at least one second")
    token = os.getenv("DEVICE_TOKEN", DEMO_TOKEN)
    outbox, rng, stop = Outbox(args.outbox), random.Random(), threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    failures = 0
    while not stop.is_set():
        reading = simulated_reading(datetime.now(UTC), rng, args.device)
        outbox.enqueue(reading)
        sent = 0
        if not args.offline:
            try:
                sent = outbox.drain(args.url, token)
                failures = 0
            except (httpx.HTTPError, ValueError):
                failures += 1
                print(json.dumps({"upload": "pending", "retry": failures}), flush=True)
        print(json.dumps({"queued": outbox.count(), "acknowledged": sent}), flush=True)
        if args.once:
            break
        stop.wait(max(args.interval, min(60, 2 ** min(failures, 6))) + rng.random())


if __name__ == "__main__":
    main()
