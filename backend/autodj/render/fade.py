"""Equal-power crossfade gains.

``cos``/``sin`` keep ``g_out² + g_in² = 1`` across the overlap, so two
correlated signals do not jump +3 dB at the midpoint.
"""

from __future__ import annotations

import numpy as np


def equal_power_gains(frame_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(outgoing, incoming)`` gain curves of length ``frame_count``.

    Frame 0 is fully outgoing; the last frame is fully incoming.
    """
    if frame_count <= 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty
    phase = np.linspace(0.0, 1.0, frame_count, endpoint=True, dtype=np.float64)
    outgoing = np.cos(0.5 * np.pi * phase).astype(np.float32)
    incoming = np.sin(0.5 * np.pi * phase).astype(np.float32)
    return outgoing, incoming
