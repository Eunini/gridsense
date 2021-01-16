# Observation contract

Submit `POST /api/readings/batch` with `X-Device-Token` and a JSON object containing `readings`.

| Field | Type and meaning |
|---|---|
| `event_id` | UUID, immutable for all retries of an observation |
| `device_id` | Registered device ID; 1–64 letters, digits, `_`, or `-` |
| `recorded_at` | ISO 8601 timestamp with timezone; normalized to UTC |
| `grid_voltage_v` | Grid voltage, 0–300 V |
| `load_w` | Total consumption, 0–100,000 W |
| `solar_w` | Solar generation, 0–100,000 W |
| `battery_soc_pct` | Battery state of charge, 0–100% |
| `battery_power_w` | Positive for discharge, negative for charge; ±100,000 W |

Unknown fields, non-finite numbers, naive timestamps, and observations more than five minutes into the future are rejected. Historical observations are allowed. The server accepts delayed upload without moving observation timestamps to the arrival time.

Successful replies contain `accepted`, `duplicates`, and the exact submitted `event_ids`. A device should clear only those entries after checking the full acknowledgement. The same UUID with different values produces HTTP 409. A batch containing an unregistered device or invalid credential produces HTTP 401.

## Synthetic catalog

Scenario files are JSONL with one observation per line. Each day has 96 quarter-hour observations. IDs are deterministic UUIDv5 values derived from device and observation time; the generator is seeded by scenario date.

The dates, voltage patterns, solar curves, load spikes, and battery levels are simulated. They do not establish historical energy conditions in Lagos or performance on real equipment. The catalog is useful for replay, idempotency checks, and sample-resolution behavior; it is not an empirical benchmark dataset.

`data/scenarios/index.json` records each file's sample count and SHA-256. To reproduce a day, use `day_samples()` and `encode()` from `scripts/generate_scenarios.py` with the catalog's generator seed. To verify a downloaded catalog, recompute the file hashes and validate every line with `gridsense.schemas.Reading`.
