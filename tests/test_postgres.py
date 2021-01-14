"""Exercise PostgreSQL's actual conflict-handling path in CI's disposable database."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from gridsense.schemas import Batch, Reading
from gridsense.storage import Device, Sample, Site, digest, ingest, setup_database
from sqlalchemy import delete


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="Set TEST_POSTGRES_URL for PostgreSQL integration"
)
def test_postgres_auth_and_idempotent_replay():
    engine, sessions = setup_database(os.environ["TEST_POSTGRES_URL"])
    device_id = "ci-" + uuid4().hex
    with sessions() as session:
        site = Site(name="CI integration", location="Synthetic test")
        session.add(site)
        session.flush()
        session.add(Device(id=device_id, site_id=site.id, token_hash=digest("ci-only-device")))
        session.commit()
        row = Reading(
            event_id=uuid4(),
            device_id=device_id,
            recorded_at=datetime.now(UTC),
            grid_voltage_v=230,
            load_w=1000,
            solar_w=1200,
            battery_soc_pct=60,
            battery_power_w=-200,
        )
        try:
            batch = Batch(readings=[row])
            assert ingest(session, batch, "ci-only-device")["accepted"] == 1
            assert ingest(session, batch, "ci-only-device")["duplicates"] == 1
        finally:
            session.rollback()
            session.execute(delete(Sample).where(Sample.device_id == device_id))
            session.execute(delete(Device).where(Device.id == device_id))
            session.execute(delete(Site).where(Site.id == site.id))
            session.commit()
    engine.dispose()
