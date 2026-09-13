from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fixtures.database import temporary_database
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from autodj.api.app import create_app
from autodj.config.settings import Settings, load_settings
from autodj.persistence.database import build_session_factory
from autodj.persistence.models import Base


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


@pytest.fixture
def fast_settings(settings: Settings, library_dir: Path) -> Settings:
    """Point at a temporary library and shorten the ingestion gates so clips can be seconds long."""
    ingestion = settings.ingestion.model_copy(
        update={"min_duration_seconds": 1.0, "validation_seconds": 1.0}
    )
    return settings.model_copy(update={"ingestion": ingestion, "audio_library_dir": library_dir})


@pytest.fixture(scope="session")
def postgres_admin_engine() -> Iterator[Engine]:
    """An AUTOCOMMIT engine used only to create and drop throwaway test databases."""
    engine = create_engine(load_settings(env_file=None).database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError as error:
        engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable, skipping database tests: {error.orig}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database_engine(postgres_admin_engine: Engine) -> Iterator[Engine]:
    """A throwaway database carrying the current schema.

    The configured database is deliberately left alone: creating and dropping its tables would
    destroy a developer's data and strand the Alembic version stamp on a schema that no longer
    exists.
    """
    with temporary_database(postgres_admin_engine, "autodj_test") as url:
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def session_factory(database_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """An empty set of tables for each test."""
    with database_engine.begin() as connection:
        connection.execute(text("truncate table tracks, track_analysis restart identity cascade"))
    yield build_session_factory(database_engine)


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def require_ffmpeg(ffmpeg_available: bool) -> None:
    if not ffmpeg_available:
        pytest.skip("ffmpeg and ffprobe are required for audio fixtures")
