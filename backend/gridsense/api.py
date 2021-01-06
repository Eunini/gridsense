import csv
import hmac
import io
import os
import random
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select, text

from .analytics import forecast, overview
from .config import DEMO_DEVICE, DEMO_TOKEN, Settings
from .schemas import Batch, Scenario
from .simulator import seed_demo, simulated_reading
from .storage import Device, Sample, Site, digest, ingest, serialize, setup_database, values


def create_app(settings=None):
    settings = settings or Settings()
    settings.validate()

    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = setup_database(settings.database_url)
        app.state.engine, app.state.sessions = engine, sessions
        if settings.demo_mode:
            with sessions() as session:
                seed_demo(session)
        else:
            with sessions() as session:
                if session.scalar(select(Device).where(Device.token_hash == digest(DEMO_TOKEN))):
                    raise RuntimeError(
                        "Public demo credentials remain in this database. Use a fresh production database."
                    )
        yield
        engine.dispose()

    app = FastAPI(
        title="GridSense",
        version="0.1.0",
        lifespan=lifespan,
        description="Offline-first telemetry. Demo measurements are synthetic.",
    )
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exception):
        # Omit raw input (including non-finite JSON numbers) from error responses.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: error[key] for key in ("loc", "msg", "type")}
                    for error in exception.errors()
                ]
            },
        )

    def session_dependency():
        with app.state.sessions() as session:
            yield session

    def operator(authorization: str = Header(default="")):
        if not settings.demo_mode and not hmac.compare_digest(
            authorization, f"Bearer {settings.operator_token}"
        ):
            raise HTTPException(401, "Operator authentication required")

    def demo_only():
        if not settings.demo_mode:
            raise HTTPException(404, "Demo tools are disabled")

    def site_data(site_id, hours, session):
        site = session.get(Site, site_id)
        if site is None:
            raise HTTPException(404, "Site not found")
        # One primary inverter per site. Additional devices are provisioned to separate sites.
        device = session.scalar(select(Device).where(Device.site_id == site_id).order_by(Device.id))
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
        samples = (
            list(
                session.scalars(
                    select(Sample)
                    .where(Sample.device_id == device.id, Sample.recorded_at >= cutoff)
                    .order_by(Sample.recorded_at.desc(), Sample.event_id.desc())
                    .limit(12_000)
                )
            )
            if device
            else []
        )
        rows = [serialize(sample) for sample in reversed(samples)]
        return site, device, rows

    @app.get("/api/health")
    def health(session=Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {"status": "ok", "demo_mode": settings.demo_mode}

    @app.get("/api/sites", dependencies=[Depends(operator)])
    def sites(session=Depends(session_dependency)):
        return [
            {
                "id": site.id,
                "name": site.name,
                "location": site.location,
                "battery_capacity_kwh": site.battery_capacity_kwh,
            }
            for site in session.scalars(select(Site).order_by(Site.id))
        ]

    @app.post("/api/readings/batch")
    def readings(
        batch: Batch, x_device_token: str = Header(default=""), session=Depends(session_dependency)
    ):
        return ingest(session, batch, x_device_token)

    @app.get("/api/sites/{site_id}/overview", dependencies=[Depends(operator)])
    def get_overview(
        site_id: int, hours: int = Query(24, ge=1, le=168), session=Depends(session_dependency)
    ):
        site, device, rows = site_data(site_id, hours, session)
        return {
            "site": {"id": site.id, "name": site.name, "location": site.location},
            "device_id": device.id if device else None,
            "hours": hours,
            "demo_mode": settings.demo_mode,
            "generated_at": datetime.now(UTC).isoformat(),
            **overview(rows, hours, site.battery_capacity_kwh),
        }

    @app.get("/api/sites/{site_id}/forecast", dependencies=[Depends(operator)])
    def get_forecast(
        site_id: int, horizon: int = Query(6, ge=1, le=24), session=Depends(session_dependency)
    ):
        _, _, rows = site_data(site_id, 168, session)
        return forecast(rows, horizon)

    @app.get("/api/sites/{site_id}/export", dependencies=[Depends(operator)])
    def export(
        site_id: int, hours: int = Query(24, ge=1, le=168), session=Depends(session_dependency)
    ):
        _, _, rows = site_data(site_id, hours, session)
        buffer = io.StringIO()
        if rows:
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="gridsense-readings.csv"'},
        )

    @app.post("/api/demo/scenario", dependencies=[Depends(demo_only)])
    def scenario(request: Scenario, session=Depends(session_dependency)):
        now = datetime.now(UTC)
        rng = random.Random()
        latest = session.scalar(
            select(Sample)
            .where(Sample.device_id == DEMO_DEVICE)
            .order_by(Sample.recorded_at.desc())
            .limit(1)
        )
        if latest and latest.recorded_at >= now.replace(tzinfo=None) - timedelta(seconds=3):
            raise HTTPException(429, "Wait three seconds between scenario changes")
        for seconds in (1, 0):
            reading = simulated_reading(
                now - timedelta(seconds=seconds), rng, scenario=request.name
            )
            session.add(Sample(**values(reading)))
        session.commit()
        return {"scenario": request.name, "inserted": 2}

    @app.post("/api/demo/reset", dependencies=[Depends(demo_only)])
    def reset(session=Depends(session_dependency)):
        session.execute(delete(Sample))
        seed_demo(session)
        return {"reset": True}

    @app.get("/api/demo/config", dependencies=[Depends(demo_only)])
    def demo_config():
        return {"device_id": DEMO_DEVICE, "device_token": DEMO_TOKEN}

    dist = Path(
        os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    )
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

        @app.get("/sw.js")
        def worker():
            return FileResponse(
                dist / "sw.js",
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
            )

        @app.get("/favicon.svg")
        def favicon():
            return FileResponse(dist / "favicon.svg")

    return app


app = create_app()
