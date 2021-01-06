import math
import random
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select

from .config import DEMO_DEVICE, DEMO_TOKEN
from .schemas import Reading
from .storage import Device, Sample, Site, digest, values


def simulated_reading(moment, rng, device_id=DEMO_DEVICE, scenario=None, deterministic=False):
    hour = (moment.astimezone(UTC).hour + 1 + moment.minute / 60) % 24
    daylight = max(0, math.sin(math.pi * (hour - 6) / 12))
    solar = max(0, 3400 * daylight * (0.85 + rng.random() * 0.15))
    load = 650 + 450 * (7 <= hour < 10) + 900 * (18 <= hour < 23) + rng.uniform(-100, 150)
    grid = 0 if (14 <= hour < 15.5 or 20 <= hour < 20.75) else rng.uniform(214, 237)
    soc = min(98, max(20, 65 + 28 * math.sin(math.pi * (hour - 9) / 12)))
    if scenario == "outage":
        grid = 0
    elif scenario == "restore":
        grid = 228
    elif scenario == "load-spike":
        load = 4800
    elif scenario == "low-battery":
        soc, grid = 14, 0
    event_id = (
        uuid5(NAMESPACE_URL, f"gridsense:{device_id}:{moment.isoformat()}")
        if deterministic
        else uuid4()
    )
    return Reading(
        event_id=event_id,
        device_id=device_id,
        recorded_at=moment,
        grid_voltage_v=round(grid, 2),
        load_w=round(load, 2),
        solar_w=round(solar, 2),
        battery_soc_pct=round(soc, 2),
        battery_power_w=round((load - solar) if grid < 180 else -min(solar * 0.3, 600), 2),
    )


def seed_demo(session, now=None):
    now = now or datetime.now(UTC)
    if session.get(Site, 1) is None:
        session.add(
            Site(id=1, name="Yaba solar lab", location="Lagos, Nigeria", battery_capacity_kwh=10.24)
        )
        session.flush()
    if session.get(Device, DEMO_DEVICE) is None:
        session.add(Device(id=DEMO_DEVICE, site_id=1, token_hash=digest(DEMO_TOKEN)))
        session.flush()
    if session.scalar(select(Sample.event_id).limit(1)) is None:
        rng = random.Random(42)
        end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        for index in range(433):
            moment = end - timedelta(minutes=10 * (432 - index))
            reading = simulated_reading(moment, rng, deterministic=True)
            if index == 408:
                reading = reading.model_copy(update={"load_w": 4400.0})
            session.add(Sample(**values(reading)))
    session.commit()
