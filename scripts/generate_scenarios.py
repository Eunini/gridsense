"""Generate deterministic, synthetic inverter fixtures; these are not field measurements."""

import argparse
import hashlib
import json
import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from gridsense.simulator import simulated_reading


def day_samples(day: date, count=96, seed=2023):
    rng = random.Random(f"{seed}:{day.isoformat()}")
    start = datetime.combine(day, time.min, tzinfo=UTC)
    rows = []
    for index in range(count):
        moment = start + timedelta(seconds=index * 86400 / count)
        scenario = "load-spike" if index == count // 3 and day.day % 7 == 0 else None
        reading = simulated_reading(moment, rng, scenario=scenario, deterministic=True)
        rows.append(reading.model_dump(mode="json"))
    return rows


def encode(rows):
    return "".join(
        json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows
    ).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    args = parser.parse_args()
    if not 1 <= args.days <= 366:
        parser.error("days must be between 1 and 366")
    args.output.mkdir(parents=True, exist_ok=True)
    entries = []
    for index in range(args.days):
        day = args.start + timedelta(days=index)
        payload = encode(day_samples(day))
        target = args.output / f"{day.isoformat()}.jsonl"
        target.write_bytes(payload)
        entries.append(
            {
                "date": day.isoformat(),
                "samples": 96,
                "file": target.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    (args.output / "index.json").write_text(
        json.dumps({"synthetic": True, "days": entries}, indent=2) + "\n"
    )
    print(f"Generated {len(entries)} synthetic scenario days in {args.output}")


if __name__ == "__main__":
    main()
