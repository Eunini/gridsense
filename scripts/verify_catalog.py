"""Verify catalog hashes, schema validity, event uniqueness, and declared sample counts."""

import hashlib
import json
from pathlib import Path

from gridsense.schemas import Reading


def main():
    base = Path(__file__).resolve().parents[1] / "data/scenarios"
    catalog = json.loads((base / "index.json").read_text())
    seen, count = set(), 0
    for entry in catalog["days"]:
        file = (base / entry["file"]).resolve()
        if not file.is_relative_to(base.resolve()):
            raise ValueError("Scenario path escapes catalog directory")
        payload = file.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise ValueError(f"Hash mismatch: {entry['file']}")
        rows = [Reading.model_validate_json(line) for line in payload.splitlines() if line]
        if len(rows) != entry["samples"]:
            raise ValueError("Sample count mismatch")
        for row in rows:
            if row.event_id in seen or row.recorded_at.date().isoformat() != entry["date"]:
                raise ValueError("Duplicate event or incorrect scenario date")
            seen.add(row.event_id)
            count += 1
    print(
        f"PASS: {len(catalog['days'])} scenario days, {count} valid unique synthetic observations"
    )


if __name__ == "__main__":
    main()
