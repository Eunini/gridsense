from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from gridsense.edge import Outbox


def event():
    return {
        "event_id": str(uuid4()),
        "device_id": "inverter-01",
        "recorded_at": datetime.now(UTC).isoformat(),
        "load_w": 100,
        "solar_w": 50,
        "battery_soc_pct": 65,
        "battery_power_w": 50,
        "grid_voltage_v": 230,
    }


def test_queue_survives_restart_and_network_failure(tmp_path):
    path = tmp_path / "edge.db"
    Outbox(path).enqueue(event())
    resumed = Outbox(path)
    assert resumed.count() == 1

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(httpx.ConnectError):
            resumed.drain("http://test", "demo", client)
    assert Outbox(path).count() == 1


def test_only_exact_acknowledgements_remove_pending_events(tmp_path):
    queue, row = Outbox(tmp_path / "queue.db"), event()
    queue.enqueue(row)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"accepted": 1, "event_ids": []})
        )
    ) as client:
        with pytest.raises(ValueError):
            queue.drain("http://test", "demo", client)
    assert queue.count() == 1
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"duplicates": 1, "event_ids": [row["event_id"]]})
        )
    ) as client:
        assert queue.drain("http://test", "demo", client) == 1
    assert queue.count() == 0


def test_local_idempotency_prevents_overwriting_a_queued_event(tmp_path):
    queue, row = Outbox(tmp_path / "queue.db"), event()
    queue.enqueue(row)
    queue.enqueue(row)
    assert queue.count() == 1
    with pytest.raises(ValueError):
        queue.enqueue({**row, "load_w": 200})
