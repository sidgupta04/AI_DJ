import numpy as np
import pytest

from autodj.render.session import append_transition


def test_continuous_mix_keeps_intro_body_and_tail() -> None:
    a = np.ones((100, 2), dtype=np.float32)
    b = np.full((100, 2), 0.5, dtype=np.float32)
    mixed = append_transition(
        a, b, exit_sample=60, entry_sample=10, fade_frames=10, earliest_exit=0
    )
    assert mixed.shape == (150, 2)
    np.testing.assert_array_equal(mixed[:60], a[:60])
    np.testing.assert_allclose(mixed[60], 1)
    np.testing.assert_allclose(mixed[69:], 0.5, atol=1e-6)
    c = np.full((100, 2), 0.25, dtype=np.float32)
    chained = append_transition(
        mixed, c, exit_sample=120, entry_sample=10, fade_frames=10, earliest_exit=70
    )
    np.testing.assert_array_equal(chained[:120], mixed[:120])
    assert len(chained) == 210


@pytest.mark.parametrize(
    "exit_sample,entry,fade,earliest",
    [
        (50, 0, 10, 60),
        (95, 0, 10, 0),
        (60, 95, 10, 0),
        (60, -1, 10, 0),
    ],
)
def test_backward_or_short_overlap_is_rejected(
    exit_sample: int,
    entry: int,
    fade: int,
    earliest: int,
) -> None:
    with pytest.raises(ValueError, match="INSUFFICIENT_SESSION_WINDOW"):
        append_transition(
            np.ones((100, 2)),
            np.ones((100, 2)),
            exit_sample=exit_sample,
            entry_sample=entry,
            fade_frames=fade,
            earliest_exit=earliest,
        )
