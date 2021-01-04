from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: UUID
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    recorded_at: datetime
    grid_voltage_v: float = Field(ge=0, le=300)
    load_w: float = Field(ge=0, le=100_000)
    solar_w: float = Field(ge=0, le=100_000)
    battery_soc_pct: float = Field(ge=0, le=100)
    battery_power_w: float = Field(ge=-100_000, le=100_000)

    @field_validator("recorded_at")
    @classmethod
    def aware_and_not_future(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("recorded_at is more than five minutes in the future")
        return value.astimezone(UTC)


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readings: list[Reading] = Field(min_length=1, max_length=500)


class Scenario(BaseModel):
    name: str = Field(pattern=r"^(outage|restore|load-spike|low-battery)$")
