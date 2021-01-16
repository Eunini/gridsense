# Synthetic inverter scenarios

Every JSONL file in this catalog is generated data. The dates identify simulation scenarios; they do not describe when measurements were collected from hardware.

Each day contains 96 quarter-hour observations. The complete catalog is indexed by `index.json`, including sample counts, a reproducible generator seed, and file SHA-256 values. Validate the catalog with:

```bash
uv run python scripts/verify_catalog.py
```

Replay any day through the persistent edge outbox:

```bash
uv run python scripts/replay_scenario.py data/scenarios/YEAR/MM-DD.jsonl --now
```

Replace `YEAR/MM-DD` with a path from the index. Historical fixture increments also serve the repository owner's disclosed contribution-calendar reconstruction. See `docs/provenance.json` for the actual project creation date.
