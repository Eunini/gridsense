"""Replay a synthetic JSONL fixture through the same durable outbox used by devices."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from gridsense.config import DEMO_TOKEN
from gridsense.edge import Outbox
from gridsense.schemas import Reading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--now", action="store_true", help="Shift the scenario to end one minute ago"
    )
    parser.add_argument("--outbox", default="data/runtime/replay.db")
    args = parser.parse_args()
    rows = [
        Reading.model_validate(json.loads(line))
        for line in args.file.read_text().splitlines()
        if line.strip()
    ]
    if not rows:
        parser.error("Fixture is empty")
    offset = datetime.now(UTC) - timedelta(minutes=1) - max(row.recorded_at for row in rows)
    queue = Outbox(args.outbox)
    for row in rows:
        if args.now:
            when = row.recorded_at + offset
            row = row.model_copy(
                update={
                    "recorded_at": when,
                    "event_id": uuid5(
                        NAMESPACE_URL, f"gridsense-replay:{row.event_id}:{when.isoformat()}"
                    ),
                }
            )
        queue.enqueue(row)
    sent = 0
    while queue.count():
        sent += queue.drain(args.url, os.getenv("DEVICE_TOKEN", DEMO_TOKEN))
    print(f"Acknowledged {sent} synthetic readings; outbox empty.")


if __name__ == "__main__":
    main()
