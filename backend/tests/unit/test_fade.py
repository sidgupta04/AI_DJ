from __future__ import annotations

import numpy as np
import pytest

from autodj.render.fade import equal_power_gains


def test_equal_power_gains_start_outgoing_and_end_incoming() -> None:
    outgoing, incoming = equal_power_gains(9)
    assert outgoing[0] == pytest.approx(1.0)
    assert incoming[0] == pytest.approx(0.0)
    assert outgoing[-1] == pytest.approx(0.0)
    assert incoming[-1] == pytest.approx(1.0)


def test_equal_power_gains_sum_of_squares_is_one() -> None:
    outgoing, incoming = equal_power_gains(64)
    power = outgoing.astype(np.float64) ** 2 + incoming.astype(np.float64) ** 2
    np.testing.assert_allclose(power, 1.0, atol=1e-6)
