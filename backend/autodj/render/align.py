"""Beat-index alignment for a constant-tempo mix.

M2 stores a beat grid, not detected downbeats. When ``align_on_downbeat`` is set,
the coincidence beat is the first inferred 4/4 bar boundary inside the planned
region (``beat_index % 4 == 0``, treating beat 0 as bar 1) so bars line up.
"""

from __future__ import annotations

# Inferred 4/4 bar phase on the M2 beat grid. Not a downbeat detector.
BEATS_PER_BAR = 4


def alignment_beat_index(
    start_beat: int,
    end_beat: int,
    beat_count: int,
    *,
    align_on_downbeat: bool,
    beats_per_bar: int = BEATS_PER_BAR,
) -> int:
    """Return the beat index that should coincide with the other track's beat.

    ``end_beat`` is exclusive, matching stored regions (``[start, end)``). Falls
    back to ``start_beat`` when the region contains no bar-phase boundary.
    """
    last = min(end_beat, beat_count)
    start = start_beat
    if start < 0:
        start = 0
    if last <= 0:
        return 0
    if start >= last:
        return min(start, beat_count - 1) if beat_count else 0
    if not align_on_downbeat:
        return start

    remainder = start % beats_per_bar
    candidate = start if remainder == 0 else start + (beats_per_bar - remainder)
    if candidate < last:
        return candidate
    return start
