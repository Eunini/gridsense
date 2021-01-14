from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from gridsense.config import DEMO_TOKEN


def sample(**changes):
    return {
        "event_id": str(uuid4()),
        "device_id": "inverter-01",
        "recorded_at": datetime.now(UTC).isoformat(),
        "grid_voltage_v": 230,
        "load_w": 900,
        "solar_w": 1200,
        "battery_soc_pct": 65,
        "battery_power_w": -300,
        **changes,
    }


def send(client, readings, token=DEMO_TOKEN):
    return client.post(
        "/api/readings/batch", json={"readings": readings}, headers={"X-Device-Token": token}
    )


def test_replay_is_idempotent_and_payload_conflicts_are_rejected(client):
    row = sample()
    assert send(client, [row]).json()["accepted"] == 1
    assert send(client, [row]).json()["duplicates"] == 1
    assert send(client, [{**row, "load_w": 901}]).status_code == 409
    assert send(client, [row]).json()["duplicates"] == 1


def test_conflicting_batch_rolls_back_new_events(client):
    old, new = sample(), sample()
    send(client, [old])
    assert send(client, [new, {**old, "solar_w": 20}]).status_code == 409
    assert send(client, [new]).json()["accepted"] == 1


def test_authentication_applies_to_every_device_in_batch(client):
    assert send(client, [sample()], token="wrong").status_code == 401
    assert send(client, [sample(), sample(device_id="another-device")]).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"recorded_at": "2023-01-01T10:00:00"},
        {"battery_soc_pct": 110},
        {"load_w": -1},
        {"unexpected": 1},
        {"recorded_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    ],
)
def test_invalid_readings_are_rejected(client, changes):
    assert send(client, [sample(**changes)]).status_code == 422


def test_out_of_order_events_do_not_replace_latest_reading(client):
    newest = sample(load_w=2345)
    older = sample(recorded_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(), load_w=100)
    send(client, [newest, older])
    overview = client.get("/api/sites/1/overview").json()
    assert overview["current"]["event_id"] == newest["event_id"]


def test_scenarios_and_exports_work(client):
    assert client.post("/api/demo/scenario", json={"name": "outage"}).status_code == 200
    overview = client.get("/api/sites/1/overview").json()
    assert overview["current"]["grid_voltage_v"] == 0
    assert overview["outages"][0]["ongoing"] is True
    csv = client.get("/api/sites/1/export")
    assert csv.status_code == 200
    assert "event_id" in csv.text and "text/csv" in csv.headers["content-type"]
    forecast = client.get("/api/sites/1/forecast").json()
    assert len(forecast["points"]) == 12
    assert forecast["backtest"]["holdout_samples"] == 12


def test_missing_sites_and_oversized_batches(client):
    assert client.get("/api/sites/999/overview").status_code == 404
    assert send(client, []).status_code == 422
    assert send(client, [sample()] * 501).status_code == 422
