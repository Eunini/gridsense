import pytest
from fastapi.testclient import TestClient
from gridsense.api import create_app
from gridsense.config import DEMO_TOKEN, Settings


def test_production_requires_operator_auth_and_disables_all_demo_tools(tmp_path):
    token = "unit-test-operator-" + "x" * 32
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'production.db'}",
            demo_mode=False,
            operator_token=token,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/sites").status_code == 401
        assert client.get("/api/sites", headers={"Authorization": "Bearer " + token}).json() == []
        assert client.get("/api/demo/config").status_code == 404
        assert client.post("/api/demo/reset").status_code == 404
        assert client.post("/api/demo/scenario", json={"name": "outage"}).status_code == 404


def test_production_rejects_a_reused_public_demo_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'demo.db'}"
    with TestClient(create_app(Settings(database_url=url, demo_mode=True))):
        pass
    app = create_app(Settings(database_url=url, demo_mode=False, operator_token="x" * 40))
    with pytest.raises(RuntimeError, match="Public demo credentials"):
        with TestClient(app):
            pass


def test_no_production_seed_and_no_weak_operator_token():
    with pytest.raises(ValueError, match="OPERATOR_TOKEN"):
        create_app(Settings(demo_mode=False, operator_token=""))


def test_nonfinite_json_numbers_receive_a_validation_error(client):
    response = client.post(
        "/api/readings/batch",
        content="""{"readings":[{
      "event_id":"41b1be3d-8d48-4a36-9124-a4cb2e4eff29","device_id":"inverter-01",
      "recorded_at":"2023-01-01T00:00:00Z","grid_voltage_v":230,"load_w":NaN,
      "solar_w":100,"battery_soc_pct":50,"battery_power_w":0}]}""",
        headers={"Content-Type": "application/json", "X-Device-Token": DEMO_TOKEN},
    )
    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]
