from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autodj.api.app import create_app
from autodj.config.settings import Settings, load_settings


@pytest.fixture
def settings() -> Settings:
    """Settings from ``default.yaml`` only, ignoring any developer ``.env``."""
    return load_settings(env_file=None)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def library_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "library"
    directory.mkdir()
    return directory


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def require_ffmpeg(ffmpeg_available: bool) -> None:
    if not ffmpeg_available:
        pytest.skip("ffmpeg and ffprobe are required for audio fixtures")
