from __future__ import annotations

from autodj.render.align import alignment_beat_index


def test_alignment_uses_the_region_start_when_bar_phase_snap_is_off() -> None:
    assert alignment_beat_index(6, 38, 80, align_on_downbeat=False) == 6


def test_alignment_snaps_forward_to_the_next_inferred_bar_phase() -> None:
    # M2 has no downbeat detector: index % 4 == 0 is inferred 4/4 bar phase.
    assert alignment_beat_index(6, 38, 80, align_on_downbeat=True) == 8


def test_alignment_keeps_a_start_that_is_already_on_bar_phase() -> None:
    assert alignment_beat_index(8, 40, 80, align_on_downbeat=True) == 8


def test_alignment_falls_back_when_the_region_has_no_bar_phase_beat() -> None:
    assert alignment_beat_index(6, 8, 80, align_on_downbeat=True) == 6
