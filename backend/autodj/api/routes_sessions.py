"""HTTP boundary for synchronous, pre-rendered local DJ sessions."""

from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from autodj.services.sessions import SessionService, open_session_service

router = APIRouter(tags=["sessions"])


def session_service(request: Request) -> Iterator[SessionService]:
    service, engine = open_session_service(request.app.state.settings)
    try:
        yield service
    finally:
        engine.dispose()


Service = Annotated[SessionService, Depends(session_service)]


class SessionRequest(BaseModel):
    seed_track_id: int = Field(gt=0, strict=True)
    length: int | None = Field(default=None, ge=2, strict=True)


@router.get("/tracks")
def tracks(service: Service) -> dict[str, Any]:
    return service.tracks()


@router.post("/sessions", status_code=201)
def create_session(body: SessionRequest, service: Service) -> dict[str, Any]:
    try:
        return service.create(body.seed_track_id, body.length)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/sessions/{identifier}")
def get_session(identifier: UUID, service: Service) -> dict[str, Any]:
    result = service.get(str(identifier))
    if result is None:
        raise HTTPException(404, "Session not found")
    return result


@router.get("/sessions/{identifier}/audio")
def session_audio(identifier: UUID, service: Service) -> FileResponse:
    result = get_session(identifier, service)
    if result["status"] not in ("READY", "PARTIAL"):
        raise HTTPException(409, "Session audio is not ready")
    path = service.audio_path(str(identifier))
    if not path.is_file():
        raise HTTPException(404, "Rendered audio is no longer available")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"autodj-{identifier}.wav",
        content_disposition_type="inline",
    )
