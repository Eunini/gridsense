import importlib.util
from datetime import date
from pathlib import Path

from gridsense.schemas import Reading

spec = importlib.util.spec_from_file_location(
    "generator", Path(__file__).parents[1] / "scripts/generate_scenarios.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_scenario_generation_is_reproducible_valid_and_has_both_grid_states():
    first = generator.day_samples(date(2023, 3, 12))
    assert first == generator.day_samples(date(2023, 3, 12))
    readings = [Reading.model_validate(row) for row in first]
    assert len(readings) == 96
    assert len({row.event_id for row in readings}) == 96
    assert any(row.grid_voltage_v == 0 for row in readings)
    assert any(row.grid_voltage_v > 205 for row in readings)
