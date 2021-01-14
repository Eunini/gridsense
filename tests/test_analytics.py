from datetime import UTC, datetime, timedelta

import pytest
from gridsense.analytics import anomalies, forecast, outage_events, overview, predict


def series(voltages, step=10, load=1000):
    start = datetime(2023, 7, 1, tzinfo=UTC)
    return [
        {
            "event_id": str(index),
            "recorded_at": (start + timedelta(minutes=index * step)).isoformat(),
            "grid_voltage_v": voltage,
            "load_w": load,
            "solar_w": 500,
            "battery_soc_pct": 60,
            "battery_power_w": 500,
        }
        for index, voltage in enumerate(voltages)
    ]


def test_outages_require_two_observations_and_voltage_hysteresis():
    assert outage_events(series([230, 0, 230])) == []
    result = outage_events(series([230, 0, 0, 195, 220, 220]))
    assert len(result) == 1
    assert result[0]["duration_minutes"] == 30
    assert result[0]["ongoing"] is False


def test_offline_gaps_are_not_reported_as_power_outages():
    rows = series([0, 0, 230, 230])
    for row in rows[2:]:
        row["recorded_at"] = (
            datetime.fromisoformat(row["recorded_at"]) + timedelta(hours=3)
        ).isoformat()
    result = outage_events(rows)
    assert result[0]["duration_minutes"] == 10
    assert result[0]["interrupted_by_gap"] is True
    summary = overview(rows, 4, 10)["summary"]
    assert summary["observed_hours"] == pytest.approx(0.33, abs=0.01)
    assert summary["coverage_pct"] < 10


def test_trapezoidal_energy_integrates_only_observed_intervals():
    rows = series([230] * 7)
    result = overview(rows, 1, 10)
    assert result["summary"]["load_kwh"] == 1
    assert result["summary"]["solar_kwh"] == 0.5
    assert result["summary"]["grid_availability_pct"] == 100


def test_robust_load_spike_detection_and_low_reserve():
    rows = series([230] * 14)
    rows[-1].update(load_w=5000, battery_soc_pct=12)
    assert {alert["kind"] for alert in anomalies(rows)} == {"load-spike", "low-battery"}


def test_forecast_uses_no_future_observations():
    rows = series([230] * 25)
    target = datetime.fromisoformat(rows[-1]["recorded_at"])
    first = predict(rows, [target])
    rows[-1]["load_w"] = 99_999
    assert predict(rows, [target]) == first
    assert forecast(rows[:5])["method"] == "insufficient-data"
    assert forecast([])["points"] == []


def test_empty_and_stale_states_are_explicit():
    assert overview([], 24, 10)["stale"] is True
    assert overview([], 24, 10)["summary"]["grid_availability_pct"] is None
    assert overview(series([230]), 24, 10)["stale"] is True
