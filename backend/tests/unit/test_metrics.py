from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from autodj.metrics.summary import distribution, sign_test, summarize
from autodj.metrics.transition import alignment_error, energy_discontinuity_db


def _alignment(a: np.ndarray, b: np.ndarray) -> float | None:
    return alignment_error(
        a,
        b,
        sample_rate=1000,
        hop_ms=5,
        max_lag_ms=200,
        session_bpm=120,
        min_correlation=0.1,
        silence_floor_dbfs=-90,
    ).error_ms


@pytest.mark.parametrize("shift", [0, 25, 80, -40])
def test_alignment_measures_pcm_shift_not_planned_beats(shift: int) -> None:
    a = np.zeros(5000)
    a[np.arange(300, 4500, 500)] = 0.5
    b = np.roll(a, shift)
    assert _alignment(a, b) == pytest.approx(abs(shift), abs=5)


def test_silence_and_constant_audio_are_not_perfect_alignment() -> None:
    assert _alignment(np.zeros(1000), np.zeros(1000)) is None
    assert _alignment(np.ones(1000), np.ones(1000)) is None
    assert _alignment(np.zeros(1), np.zeros(1)) is None


def test_antiphase_stereo_does_not_cancel_onset_power() -> None:
    a = np.zeros(4000)
    a[np.arange(300, 3500, 500)] = 0.5
    stereo = np.column_stack((a, -a))
    assert _alignment(stereo, np.roll(stereo, 50, axis=0)) == pytest.approx(50, abs=5)


def test_nonfinite_pcm_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        _alignment(np.full(100, np.nan), np.ones(100))


def test_energy_discontinuity_has_db_units_and_silence_floor() -> None:
    audio = np.concatenate((np.full(1000, 0.1), np.full(1000, 0.2)))
    assert energy_discontinuity_db(
        audio, sample_rate=1000, window_seconds=1, floor_dbfs=-90
    ) == pytest.approx(6.0206, abs=0.001)
    assert (
        energy_discontinuity_db(np.zeros(2000), sample_rate=1000, window_seconds=1, floor_dbfs=-90)
        == 0
    )


def test_distributions_and_failure_denominators_include_missing() -> None:
    assert distribution([None, 1, 3])["p50"] == 2
    assert distribution([None])["p95"] is None
    rows: list[dict[str, Any]] = [
        {"strategy": "D", "status": "FAILED", "failure_reason": "NO_PLAN"},
        {"strategy": "D", "status": "RENDERED", "failure_reason": None, "alignment_error_ms": 20},
    ]
    summary = summarize(rows)["D"]
    assert summary["success_rate"] == 0.5
    assert summary["failures_by_reason"] == {"NO_PLAN": 1}
    assert summary["distributions"]["alignment_error_ms"]["missing"] == 1


def test_exact_sign_test_excludes_absent_votes() -> None:
    assert sign_test(0, 0) is None
    assert sign_test(3, 3) == 1
    assert sign_test(6, 0) == pytest.approx(0.03125)
