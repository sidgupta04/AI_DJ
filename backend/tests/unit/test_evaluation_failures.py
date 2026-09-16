"""Evaluation must not overwrite an earlier result or retain its own failed publish."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.orm import sessionmaker

from autodj.config.settings import Settings
from autodj.dj.baselines import Strategy
from autodj.dj.types import TrackCandidate
from autodj.render.types import RenderedMix
from autodj.services.evaluation import EvaluationService


def _track(identifier: int) -> TrackCandidate:
    return TrackCandidate(identifier, "missing.wav", 120, 0.5, 1, 2, 60, [], [0, 0.5], 2)


def test_existing_output_is_preserved(settings: Settings, tmp_path: Path) -> None:
    output = tmp_path / "existing.wav"
    output.write_bytes(b"existing output")
    result = EvaluationService(settings).evaluate(
        _track(1),
        [_track(2)],
        strategy=Strategy.NEAREST_BPM,
        seed=1,
        output=output,
    )
    assert result["failure_reason"] == "FileExistsError"
    assert result["wav_path"] is None
    assert output.read_bytes() == b"existing output"


def test_persistence_failure_discards_only_new_output(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EvaluationService(settings, sessionmaker())
    audio = np.ones((1000, 2), dtype=np.float32) * 0.1
    mix = RenderedMix(
        audio, 1000, -20, False, False, 1, 1, 100, 800, audio[100:900], audio[100:900]
    )
    monkeypatch.setattr(service, "_render", lambda *_args: mix)

    def fail(*_args: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_persist", fail)
    output = tmp_path / "attempt.wav"
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.evaluate(
            _track(1), [_track(2)], strategy=Strategy.NEAREST_BPM, seed=1, output=output
        )
    assert not output.exists()
