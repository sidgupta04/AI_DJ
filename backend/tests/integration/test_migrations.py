"""The Alembic revision must apply, reverse, and re-apply on a clean database."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fixtures.database import temporary_database
from sqlalchemy import Engine, create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def scratch_database_url(postgres_admin_engine: Engine) -> Iterator[str]:
    """A throwaway database so migrations never race the schema other tests rely on."""
    with temporary_database(postgres_admin_engine, "autodj_migration") as url:
        yield url


def _alembic(command: str, database_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, "head" if command == "upgrade" else "base"],
        cwd=REPO_ROOT,
        env={**os.environ, "AUTODJ_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic {command} failed: {result.stderr}"


def _table_names(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _enum_type_names(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("select typname from pg_type where typtype = 'e'")
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


def test_migration_applies_reverses_and_reapplies(scratch_database_url: str) -> None:
    _alembic("upgrade", scratch_database_url)

    assert {"tracks", "track_analysis"} <= _table_names(scratch_database_url)
    assert {"analysis_status", "metadata_source"} <= _enum_type_names(scratch_database_url)

    _alembic("downgrade", scratch_database_url)

    assert "tracks" not in _table_names(scratch_database_url)
    assert "track_analysis" not in _table_names(scratch_database_url)
    # Enum types must go too, otherwise re-applying fails with "type already exists".
    assert not {"analysis_status", "metadata_source"} & _enum_type_names(scratch_database_url)

    _alembic("upgrade", scratch_database_url)

    assert {"tracks", "track_analysis"} <= _table_names(scratch_database_url)


def test_schema_matches_the_models(scratch_database_url: str) -> None:
    _alembic("upgrade", scratch_database_url)
    engine = create_engine(scratch_database_url)
    try:
        tracks_columns = {column["name"] for column in inspect(engine).get_columns("tracks")}
        analysis_columns = {
            column["name"] for column in inspect(engine).get_columns("track_analysis")
        }
    finally:
        engine.dispose()

    assert tracks_columns == {
        "id",
        "audio_path",
        "content_hash",
        "title",
        "artist",
        "metadata_source",
        "duration_seconds",
        "native_sample_rate",
        "channels",
        "codec_name",
        "bit_rate",
        "analysis_status",
        "failure_reason",
        "native_bpm",
        "analysis_confidence",
        "analysis_version",
        "created_at",
        "updated_at",
    }
    assert analysis_columns == {
        "id",
        "track_id",
        "beat_times",
        "beat_count",
        "sample_rate",
        "hop_length",
        "refine_hop_length",
        "median_ibi_seconds",
        "ibi_cv",
        "onset_contrast",
        "tempo_octave_factor",
        "created_at",
        "updated_at",
    }
