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


def _alembic(command: str, database_url: str, target: str | None = None) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            command,
            target or ("head" if command == "upgrade" else "base"),
        ],
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

    assert {"tracks", "track_analysis", "transitions", "dj_sessions"} <= _table_names(
        scratch_database_url
    )
    assert {"analysis_status", "metadata_source", "transition_status"} <= _enum_type_names(
        scratch_database_url
    )

    _alembic("downgrade", scratch_database_url)

    assert "tracks" not in _table_names(scratch_database_url)
    assert "track_analysis" not in _table_names(scratch_database_url)
    assert "transitions" not in _table_names(scratch_database_url)
    assert "dj_sessions" not in _table_names(scratch_database_url)
    # Enum types must go too, otherwise re-applying fails with "type already exists".
    assert not {"analysis_status", "metadata_source", "transition_status"} & _enum_type_names(
        scratch_database_url
    )

    _alembic("upgrade", scratch_database_url)

    assert {"tracks", "track_analysis", "transitions"} <= _table_names(scratch_database_url)


def test_schema_matches_the_models(scratch_database_url: str) -> None:
    _alembic("upgrade", scratch_database_url)
    engine = create_engine(scratch_database_url)
    try:
        tracks_columns = {column["name"] for column in inspect(engine).get_columns("tracks")}
        analysis_columns = {
            column["name"] for column in inspect(engine).get_columns("track_analysis")
        }
        transition_columns = {
            column["name"] for column in inspect(engine).get_columns("transitions")
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
        "energy",
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
        "energy_curve",
        "energy_curve_hz",
        "energy_scalar",
        "stable_regions",
        "created_at",
        "updated_at",
    }
    assert transition_columns == {
        "strategy",
        "evaluation",
        "bpm_delta",
        "stretch_percent_a",
        "stretch_percent_b",
        "alignment_error_ms",
        "alignment_correlation",
        "energy_discontinuity_db",
        "region_stability_a",
        "region_stability_b",
        "planning_seconds",
        "render_seconds",
        "measurement_seconds",
        "id",
        "track_a_id",
        "track_b_id",
        "session_bpm",
        "stretch_ratio",
        "outgoing_start_beat",
        "outgoing_end_beat",
        "incoming_start_beat",
        "incoming_end_beat",
        "pair_cost",
        "stability_cost",
        "energy_cost",
        "stretch_cost",
        "position_cost",
        "wav_path",
        "peak_dbfs",
        "peak_exceeded",
        "clipped",
        "status",
        "failure_reason",
        "config_snapshot",
        "created_at",
        "updated_at",
    }


def test_m6_upgrade_leaves_historical_measurements_null(scratch_database_url: str) -> None:
    _alembic("upgrade", scratch_database_url, "e7b2c91d4a08")
    engine = create_engine(scratch_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                insert into tracks (
                    id, audio_path, content_hash, title, metadata_source, analysis_status
                )
                values (1, 'old-a.wav', 'abc', 'A', 'filename', 'COMPLETE'),
                       (2, 'old-b.wav', 'def', 'B', 'filename', 'COMPLETE')
            """)
            )
            connection.execute(
                text("""
                insert into transitions (
                    track_a_id, track_b_id, session_bpm, stretch_ratio,
                    outgoing_start_beat, outgoing_end_beat, incoming_start_beat, incoming_end_beat,
                    pair_cost, stability_cost, energy_cost, stretch_cost, position_cost,
                    peak_exceeded, clipped, status, config_snapshot
                ) values (1, 2, 120, 1, 0, 32, 0, 32, 0, 0, 0, 0, 0,
                          false, false, 'RENDERED', '{}')
            """)
            )
        _alembic("upgrade", scratch_database_url)
        with engine.connect() as connection:
            row = connection.execute(
                text("select status, alignment_error_ms, strategy, evaluation from transitions")
            ).one()
            assert tuple(row) == ("RENDERED", None, None, None)
        _alembic("downgrade", scratch_database_url, "e7b2c91d4a08")
        with engine.connect() as connection:
            assert connection.scalar(text("select count(*) from transitions")) == 1
    finally:
        engine.dispose()
