"""Actual synthetic ingestion → analysis → A–D rendering → metrics/DB → blind export."""

from __future__ import annotations

import csv
import json
import wave
from dataclasses import replace
from pathlib import Path

import pytest
from fixtures.audio import write_click_wav
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from autodj.config.settings import Settings
from autodj.dj.baselines import Strategy
from autodj.persistence.models import Transition
from autodj.services.analysis import LibraryAnalysisService
from autodj.services.evaluation import EvaluationService
from autodj.services.evaluation_tools import analyze_ratings, comparison_run
from autodj.services.ingestion import LibraryIngestionService
from autodj.services.selection import SelectionService

pytestmark = pytest.mark.usefixtures("require_ffmpeg")


def test_full_evaluation_pipeline(
    fast_settings: Settings,
    session_factory: sessionmaker[Session],
    library_dir: Path,
    tmp_path: Path,
) -> None:
    cfg = fast_settings.model_copy(
        update={
            "transition": fast_settings.transition.model_copy(
                update={
                    "crossfade_beats": 8,
                    "margin_beats": 2,
                    "outgoing_search_fraction": (0.0, 1.0),
                    "incoming_search_fraction": (0.0, 1.0),
                }
            ),
            "evaluation": fast_settings.evaluation.model_copy(update={"pair_count": 2}),
        }
    )
    for name, bpm in (("a", 124.0), ("b", 120.0)):
        write_click_wav(library_dir / f"{name}.wav", bpm=bpm, seconds=36)
    LibraryIngestionService(cfg, session_factory).scan()
    analysis = LibraryAnalysisService(cfg, session_factory).analyze()
    assert analysis.completed == 2 and analysis.failed == 0
    service = EvaluationService(cfg, session_factory)
    candidates = service.load_candidates()
    report = comparison_run(service, candidates, tmp_path / "evaluation")
    assert len(report["ladder_attempts"]) == 8
    assert report["blind_export"]["exported"] == 2
    assert "database_url" not in report["config_snapshot"]
    assert all(row["content_hash"] for row in report["tracks"])
    assert all(row["status"] == "RENDERED" for row in report["ladder_attempts"])
    assert report["ladder_summary"]["D"]["distributions"]["alignment_error_ms"]["count"] == 2
    m4 = SelectionService(cfg, session_factory).select_next(candidates[0].track_id)
    assert m4.plan is not None
    full = next(row for row in report["ladder_attempts"] if row["strategy"] == "D")
    assert full["plan"]["outgoing_region"]["start_beat"] == m4.plan.outgoing_region.start_beat
    assert full["track_b_id"] == m4.plan.track_b_id
    with session_factory() as session:
        rows = list(session.scalars(select(Transition)))
        assert len(rows) == 12
        assert all(row.render_seconds is not None and row.render_seconds > 0 for row in rows)
        assert all(row.evaluation and row.evaluation["seed"] is not None for row in rows)
        assert all(row.alignment_error_ms is not None for row in rows)
        assert all(row.region_stability_a is None for row in rows if row.strategy == "B")
    participant = tmp_path / "evaluation/blind/participants"
    assert not (participant / "codebook.json").exists()
    key = json.loads((participant.parent / "codebook.json").read_text())
    for pair_id, labels in key.items():
        assert {labels["X"], labels["Y"]} == {"B", "D"}
        sizes = []
        for label in ("X", "Y"):
            with wave.open(str(participant / f"{pair_id}_{label}.wav")) as handle:
                sizes.append(handle.getnframes())
                assert handle.getsampwidth() == 2
                assert handle.getnchannels() == 2
        assert sizes[0] == sizes[1] and sizes[0] > 0
    with (participant / "ratings.csv").open(newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 6
    with pytest.raises(ValueError, match="incomplete"):
        analyze_ratings(
            participant / "ratings.csv", participant.parent / "codebook.json", minimum_listeners=3
        )
    with pytest.raises(FileExistsError):
        comparison_run(service, candidates, tmp_path / "evaluation")

    # A missing source is retained as a failed attempt and a failed transition with null metrics.
    missing = replace(candidates[1], audio_path="vanished.wav")
    failed = service.evaluate(
        candidates[0],
        [missing],
        strategy=Strategy.NEAREST_BPM,
        seed=1,
        output=tmp_path / "missing.wav",
    )
    assert failed["status"] == "FAILED" and failed["wav_path"] is None
    with session_factory() as session:
        row = session.get(Transition, failed["transition_id"])
        assert row and row.alignment_error_ms is None and row.failure_reason


def test_no_plan_failure_is_included_in_comparison_denominator(
    settings: Settings, tmp_path: Path
) -> None:
    from autodj.dj.types import TrackCandidate
    from autodj.metrics.summary import summarize

    track = TrackCandidate(1, "none.wav", 120, 0.5, 0.9, 2, 60, [], [], 0)
    record = EvaluationService(settings).evaluate(
        track, [track], strategy=Strategy.FULL, seed=1, output=tmp_path / "none.wav"
    )
    assert record["failure_reason"] == "NO_PLAN"
    assert summarize([record])["D"]["failure_rate"] == 1
    assert not (tmp_path / "none.wav").exists()
