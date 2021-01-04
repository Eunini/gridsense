import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import DateTime, Float, ForeignKey, Index, String, create_engine, event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .schemas import Reading


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(100))
    battery_capacity_kwh: Mapped[float] = mapped_column(Float, default=10.24)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    token_hash: Mapped[str] = mapped_column(String(64))


class Sample(Base):
    __tablename__ = "readings"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    grid_voltage_v: Mapped[float] = mapped_column(Float)
    load_w: Mapped[float] = mapped_column(Float)
    solar_w: Mapped[float] = mapped_column(Float)
    battery_soc_pct: Mapped[float] = mapped_column(Float)
    battery_power_w: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("ix_device_time", "device_id", "recorded_at"),)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def setup_database(url):
    options = {}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        elif url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def values(reading: Reading):
    result = reading.model_dump()
    result["event_id"] = str(reading.event_id)
    result["recorded_at"] = reading.recorded_at.astimezone(UTC).replace(tzinfo=None)
    return result


def serialize(sample: Sample):
    return {
        column.name: (
            getattr(sample, column.name).replace(tzinfo=UTC).isoformat()
            if column.name == "recorded_at"
            else getattr(sample, column.name)
        )
        for column in Sample.__table__.columns
    }


def ingest(session, batch, token):
    device_ids = {reading.device_id for reading in batch.readings}
    devices = {
        device.id: device
        for device in session.scalars(select(Device).where(Device.id.in_(device_ids)))
    }
    if any(
        device_id not in devices
        or not hmac.compare_digest(devices[device_id].token_hash, digest(token))
        for device_id in device_ids
    ):
        raise HTTPException(401, "Invalid device credentials")
    dialect = session.bind.dialect.name
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    accepted, duplicates = 0, 0
    # One transaction per batch. Conflicting replays roll the entire batch back.
    for reading in batch.readings:
        payload = values(reading)
        query = (
            insert(Sample)
            .values(**payload)
            .on_conflict_do_nothing(index_elements=[Sample.event_id])
            .returning(Sample.event_id)
        )
        inserted = session.execute(query).scalar_one_or_none()
        if inserted is not None:
            accepted += 1
            continue
        existing = session.get(Sample, payload["event_id"])
        if any(getattr(existing, key) != value for key, value in payload.items()):
            raise HTTPException(409, "Event ID already exists with different telemetry")
        duplicates += 1
    session.commit()
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "event_ids": [str(reading.event_id) for reading in batch.readings],
    }
