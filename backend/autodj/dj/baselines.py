"""Pure next-track ordering for the evaluation model ladder."""

from __future__ import annotations

import random
from enum import StrEnum

from autodj.dj.rank import rank_candidates
from autodj.dj.types import TrackCandidate


class Strategy(StrEnum):
    RANDOM = "A"
    NEAREST_BPM = "B"
    BPM_ENERGY = "C"
    FULL = "D"


def baseline_order(
    current: TrackCandidate,
    candidates: list[TrackCandidate],
    *,
    strategy: Strategy,
    seed: int,
    session_bpm: float,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    weight_tempo: float,
    weight_energy: float,
) -> list[TrackCandidate]:
    """Candidates already meet hard render bounds; C normalizes the two M4 weights."""
    ordered = sorted(candidates, key=lambda item: item.track_id)
    if strategy == Strategy.RANDOM:
        random.Random(seed).shuffle(ordered)
        return ordered
    if strategy == Strategy.NEAREST_BPM:
        return sorted(ordered, key=lambda item: (abs(item.native_bpm - session_bpm), item.track_id))
    if strategy != Strategy.BPM_ENERGY:
        raise ValueError("full strategy uses the existing M4 planner")
    total = weight_tempo + weight_energy
    if total <= 0:
        raise ValueError("C requires a positive tempo or energy weight")
    return [
        item.candidate
        for item in rank_candidates(
            current,
            ordered,
            session_bpm=session_bpm,
            min_stretch_ratio=min_stretch_ratio,
            max_stretch_ratio=max_stretch_ratio,
            weight_tempo=weight_tempo / total,
            weight_energy=weight_energy / total,
            weight_quality=0.0,
        )
    ]
