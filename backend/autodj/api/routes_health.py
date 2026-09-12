"""Liveness and build-identity endpoint."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from autodj import __version__
from autodj.config.settings import Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_version: str
    analysis_version: int


@router.get("/health")
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        app_version=__version__,
        analysis_version=settings.analysis.version,
    )
