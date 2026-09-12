"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from autodj import __version__
from autodj.api.routes_health import router as health_router
from autodj.config.settings import Settings, get_settings
from autodj.logging_config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level, resolved.log_format)

    app = FastAPI(
        title="AutoDJ",
        version=__version__,
        summary="Automated DJ engine: offline analysis, compatibility ranking, beat-aligned mixes",
    )
    app.state.settings = resolved
    app.include_router(health_router)
    return app
