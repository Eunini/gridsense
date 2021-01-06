"""Sample-aware estimates: never count missing telemetry as a confirmed outage."""

import statistics
from datetime import UTC, datetime, timedelta

MAX_GAP_SECONDS = 20 * 60


def moment(row):
    return datetime.fromisoformat(row["recorded_at"])


def outage_events(rows):
    rows = sorted(rows, key=lambda row: (row["recorded_at"], row["event_id"]))
    events, lows, highs = [], [], []
    active = None
    previous = None
    for row in rows:
        when = moment(row)
        if previous and (when - moment(previous)).total_seconds() > MAX_GAP_SECONDS:
            if active:
                events.append(
                    {
                        "started_at": active,
                        "ended_at": previous["recorded_at"],
                        "ongoing": False,
                        "interrupted_by_gap": True,
                    }
                )
            active, lows, highs = None, [], []
        if row["grid_voltage_v"] < 180:
            highs = []
            lows.append(row)
            if active is None and len(lows) >= 2:
                active = lows[0]["recorded_at"]
        elif row["grid_voltage_v"] >= 205:
            lows = []
            highs.append(row)
            if active and len(highs) >= 2:
                events.append(
                    {
                        "started_at": active,
                        "ended_at": highs[0]["recorded_at"],
                        "ongoing": False,
                        "interrupted_by_gap": False,
                    }
                )
                active, highs = None, []
        else:
            lows, highs = [], []
        previous = row
    if active and previous:
        events.append(
            {
                "started_at": active,
                "ended_at": previous["recorded_at"],
                "ongoing": True,
                "interrupted_by_gap": False,
            }
        )
    for entry in events:
        entry["duration_minutes"] = round(
            (
                datetime.fromisoformat(entry["ended_at"])
                - datetime.fromisoformat(entry["started_at"])
            ).total_seconds()
            / 60,
            1,
        )
    return events


def anomalies(rows):
    alerts = []
    for index, row in enumerate(rows):
        baseline = [
            item["load_w"]
            for item in rows[max(0, index - 12) : index]
            if (moment(row) - moment(item)).total_seconds() <= 3 * 3600
        ]
        if len(baseline) < 6:
            continue
        median = statistics.median(baseline)
        mad = statistics.median(abs(value - median) for value in baseline)
        if row["load_w"] > median + max(4 * 1.4826 * mad, 800):
            alerts.append(
                {
                    "event_id": row["event_id"],
                    "recorded_at": row["recorded_at"],
                    "kind": "load-spike",
                    "severity": "warning",
                    "message": f"Load rose to {row['load_w'] / 1000:.2f} kW",
                    "baseline_w": round(median, 1),
                }
            )
    if rows and rows[-1]["battery_soc_pct"] < 20:
        alerts.append(
            {
                "event_id": rows[-1]["event_id"],
                "recorded_at": rows[-1]["recorded_at"],
                "kind": "low-battery",
                "severity": "critical",
                "message": f"Battery reserve is {rows[-1]['battery_soc_pct']:.0f}%",
            }
        )
    return alerts[-20:]


def overview(rows, hours, battery_capacity_kwh, now=None):
    now = now or datetime.now(UTC)
    energy = {"load_kwh": 0.0, "solar_kwh": 0.0}
    observed, available = 0.0, 0.0
    for left, right in zip(rows, rows[1:]):
        delta = (moment(right) - moment(left)).total_seconds()
        if not 0 < delta <= MAX_GAP_SECONDS:
            continue
        observed += delta
        if left["grid_voltage_v"] >= 180 and right["grid_voltage_v"] >= 180:
            available += delta
        for metric, output in [("load_w", "load_kwh"), ("solar_w", "solar_kwh")]:
            energy[output] += (left[metric] + right[metric]) / 2 * delta / 3_600_000
    current = rows[-1] if rows else None
    reserve = None
    if current and current["battery_power_w"] > 100:
        usable = max(0, current["battery_soc_pct"] - 10) / 100 * battery_capacity_kwh
        reserve = round(usable * 0.9 / (current["battery_power_w"] / 1000), 1)
    return {
        "current": current,
        "stale": not current or (now - moment(current)).total_seconds() > MAX_GAP_SECONDS,
        "last_seen": current["recorded_at"] if current else None,
        "summary": {
            **{key: round(value, 3) for key, value in energy.items()},
            "grid_availability_pct": round(100 * available / observed, 1) if observed else None,
            "coverage_pct": round(min(100, 100 * observed / (hours * 3600)), 1),
            "observed_hours": round(observed / 3600, 2),
            "battery_reserve_hours": reserve,
        },
        "outages": list(reversed(outage_events(rows))),
        "alerts": list(reversed(anomalies(rows))),
        "series": rows,
    }


def predict(rows, targets):
    """A transparent seasonal median baseline; no fitted ML or confidence claims."""
    result = []
    for target in targets:
        # Only use observations preceding the target: backtests cannot see the future.
        history = [row for row in rows if moment(row) < target]
        matching = [
            row
            for row in history
            if min(
                abs(
                    (moment(row).hour * 60 + moment(row).minute)
                    - (target.hour * 60 + target.minute)
                ),
                1440
                - abs(
                    (moment(row).hour * 60 + moment(row).minute)
                    - (target.hour * 60 + target.minute)
                ),
            )
            <= 30
        ]
        selected = matching if len(matching) >= 3 else history[-12:]
        if not selected:
            continue
        load = statistics.median(row["load_w"] for row in selected)
        solar = statistics.median(row["solar_w"] for row in selected)
        spread = max(100, statistics.median(abs(row["load_w"] - load) for row in selected) * 1.4826)
        result.append(
            {
                "recorded_at": target.isoformat(),
                "load_w": round(load, 1),
                "solar_w": round(solar, 1),
                "lower_w": round(max(0, load - 2 * spread), 1),
                "upper_w": round(load + 2 * spread, 1),
            }
        )
    return result


def forecast(rows, hours=6):
    if len(rows) < 12:
        return {
            "method": "insufficient-data",
            "points": [],
            "backtest": None,
            "note": "At least 12 observations are required.",
        }
    last = moment(rows[-1])
    points = predict(
        rows, [last + timedelta(minutes=30 * index) for index in range(1, hours * 2 + 1)]
    )
    split = max(12, len(rows) - 12)
    train, holdout = rows[:split], rows[split:]
    estimates = predict(train, [moment(row) for row in holdout])
    backtest = None
    if estimates:
        backtest = {
            "mae_w": round(
                statistics.mean(
                    abs(estimate["load_w"] - actual["load_w"])
                    for estimate, actual in zip(estimates, holdout)
                ),
                1,
            ),
            "persistence_mae_w": round(
                statistics.mean(abs(train[-1]["load_w"] - row["load_w"]) for row in holdout), 1
            ),
            "holdout_samples": len(holdout),
        }
    return {
        "method": "seasonal-median",
        "points": points,
        "backtest": backtest,
        "note": "Shading shows historical variation, not a calibrated confidence interval.",
    }
