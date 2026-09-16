"""Synthetic set → stored timeline → HTTP WAV including range playback."""

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from fixtures.audio import write_wav
from sqlalchemy.orm import Session, sessionmaker

from autodj.api.app import create_app
from autodj.api.routes_sessions import session_service
from autodj.config.settings import Settings
from autodj.dj.types import RegionInfo, TrackCandidate
from autodj.persistence.models import DJSession
from autodj.services.sessions import SessionService


@pytest.fixture
def runtime(
    settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_ffmpeg: None,
) -> SessionService:
    cfg = settings.model_copy(
        update={
            "audio_library_dir": tmp_path / "library",
            "render_cache_dir": tmp_path / "cache",
            "render": settings.render.model_copy(update={"sample_rate": 8000}),
        }
    )
    candidates = []
    for index, bpm in enumerate((120.0, 122.0, 124.0), 1):
        write_wav(cfg.audio_library_dir / f"{index}.wav", seconds=80, sample_rate=8000)
        times = [i * 60 / bpm for i in range(int(80 * bpm / 60))]
        regions = [RegionInfo(i, i + 32, times[i], times[i + 31], 0.9, 0.01, 0.5) for i in (8, 112)]
        candidates.append(
            TrackCandidate(
                index,
                f"{index}.wav",
                bpm,
                0.5,
                0.9,
                settings.analysis.version,
                80.0,
                regions,
                times,
                len(times),
            )
        )
    service = SessionService(cfg, session_factory)
    monkeypatch.setattr(
        service,
        "library",
        lambda: (
            candidates,
            {
                t.track_id: {"title": f"Track {t.track_id}", "artist": "Synthetic"}
                for t in candidates
            },
        ),
    )
    return service


def test_session_api_renders_three_tracks_once_at_seed_tempo(
    runtime: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autodj.render.stretch import PedalboardStretcher

    stretcher = Mock(wraps=PedalboardStretcher())
    monkeypatch.setattr("autodj.services.sessions.build_stretcher", lambda _: stretcher)
    app = create_app(runtime.settings)
    app.dependency_overrides[session_service] = lambda: runtime
    with TestClient(app) as client:
        assert len(client.get("/tracks").json()["tracks"]) == 3
        response = client.post("/sessions", json={"seed_track_id": 1, "length": 3})
        assert response.status_code == 201
        record = response.json()
        assert record["status"] == "READY", record
        assert record["session_bpm"] == 120
        assert [t["id"] for t in record["tracks"]] == [1, 2, 3]
        assert stretcher.stretch.call_count == 3
        assert [c.kwargs["stretch_ratio"] for c in stretcher.stretch.call_args_list] == [
            1,
            120 / 122,
            120 / 124,
        ]
        first, second = record["transitions"]
        assert second["start_seconds"] >= first["end_seconds"]
        assert record["duration_seconds"] > second["end_seconds"]
        assert client.get(f"/sessions/{record['id']}").json() == record
        audio = client.get(record["audio_url"])
        assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
        partial = client.get(record["audio_url"], headers={"Range": "bytes=0-43"})
        assert partial.status_code == 206 and len(partial.content) == 44
        runtime.audio_path(record["id"]).unlink()
        assert client.get(record["audio_url"]).status_code == 404
        assert client.get("/sessions/00000000-0000-0000-0000-000000000000").status_code == 404
        assert client.get("/sessions/not-a-uuid/audio").status_code == 422
        assert client.post("/sessions", json={"seed_track_id": 999}).status_code == 422
        assert client.post("/sessions", json={"seed_track_id": 1, "length": 1}).status_code == 422
        assert client.post("/sessions", json={"seed_track_id": 1, "length": 999}).status_code == 422
    with runtime.factory() as session:
        row = session.get(DJSession, record["id"])
        assert row and row.status == "READY"
        assert "database_url" not in row.config_snapshot


def test_exhausted_library_publishes_honest_partial_set(runtime: SessionService) -> None:
    result = runtime.create(1, 6)
    assert result["status"] == "PARTIAL"
    assert result["stop_reason"] == "NO_COMPATIBLE_TRANSITION"
    assert len(result["tracks"]) == 3 and result["audio_url"]


def test_decode_failure_is_persisted_without_audio(runtime: SessionService) -> None:
    (runtime.settings.audio_library_dir / "1.wav").unlink()
    result = runtime.create(1, 2)
    assert result["status"] == "FAILED" and result["audio_url"] is None
    assert runtime.get(result["id"]) == result
    assert not runtime.audio_path(result["id"]).exists()
    app = create_app(runtime.settings)
    app.dependency_overrides[session_service] = lambda: runtime
    with TestClient(app) as client:
        assert client.get(f"/sessions/{result['id']}/audio").status_code == 409


def test_no_candidate_fails_without_inventing_a_mix(
    runtime: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, labels = runtime.library()
    monkeypatch.setattr(runtime, "library", lambda: (candidates[:1], labels))
    result = runtime.create(1, 2)
    assert result["status"] == "FAILED" and result["audio_url"] is None
    assert result["stop_reason"] == "NO_COMPATIBLE_TRANSITION"


def test_final_persistence_failure_removes_published_audio(
    runtime: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = runtime._save
    identifiers = []

    def fail_final(record: dict[str, Any]) -> None:
        identifiers.append(record["id"])
        if record["status"] != "RENDERING":
            raise RuntimeError("database unavailable")
        saved(record)

    monkeypatch.setattr(runtime, "_save", fail_final)
    with pytest.raises(RuntimeError, match="database unavailable"):
        runtime.create(1, 2)
    assert not runtime.audio_path(identifiers[0]).exists()
