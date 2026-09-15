from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.calc_job_store import CalcJobStore
from .core.config import get_settings
from .core.import_job_store import ImportJobStore
from .core.session_store import SessionStore
from .routers import catalog, network, projects, sessions, traces, variants
from .services.dem import build_dem_providers


async def _purge_loop(app: FastAPI, interval_seconds: int) -> None:
    session_store: SessionStore = app.state.session_store
    import_job_store: ImportJobStore = app.state.import_job_store
    calc_job_store: CalcJobStore = app.state.calc_job_store
    while True:
        await asyncio.sleep(interval_seconds)
        session_store.purge_expired()
        import_job_store.purge_expired()
        calc_job_store.purge_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.session_store = SessionStore(ttl_seconds=settings.session_ttl_seconds)
    app.state.import_job_store = ImportJobStore()
    app.state.calc_job_store = CalcJobStore()
    app.state.dem_providers = build_dem_providers(settings.dem_provider)

    purge_task = asyncio.create_task(_purge_loop(app, settings.session_purge_interval_seconds))
    try:
        yield
    finally:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="HydroPS API", version=settings.software_version, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(variants.router, prefix="/api/v1")
    app.include_router(traces.router, prefix="/api/v1")
    app.include_router(network.router, prefix="/api/v1")
    app.include_router(catalog.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "active_sessions": app.state.session_store.active_session_count()}

    return app


app = create_app()
