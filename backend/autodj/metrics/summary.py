"""Distribution and paired preference statistics, with explicit missing-data counts."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any

import numpy as np


def distribution(values: Iterable[float | None]) -> dict[str, Any]:
    items = list(values)
    valid = [value for value in items if value is not None and math.isfinite(value)]
    return {
        "count": len(valid),
        "missing": len(items) - len(valid),
        "min": min(valid) if valid else None,
        "p50": float(np.percentile(valid, 50)) if valid else None,
        "p95": float(np.percentile(valid, 95)) if valid else None,
        "p99": float(np.percentile(valid, 99)) if valid else None,
        "max": max(valid) if valid else None,
    }


def summarize(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for strategy in sorted({row["strategy"] for row in attempts}):
        rows = [row for row in attempts if row["strategy"] == strategy]
        successes = sum(row["status"] == "RENDERED" for row in rows)
        failures = Counter(row["failure_reason"] for row in rows if row["status"] != "RENDERED")
        names = (
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
        )
        result[strategy] = {
            "attempts": len(rows),
            "successes": successes,
            "success_rate": successes / len(rows),
            "failure_rate": 1 - successes / len(rows),
            "failures_by_reason": dict(failures),
            "distributions": {name: distribution(row.get(name) for row in rows) for name in names},
        }
    return result


def sign_test(wins: int, losses: int) -> float | None:
    """Exact two-sided paired sign test. Ties excluded by caller; no votes means unavailable."""
    if wins < 0 or losses < 0:
        raise ValueError("counts must be nonnegative")
    count = wins + losses
    if not count:
        return None
    return min(1.0, 2 * sum(math.comb(count, i) for i in range(min(wins, losses) + 1)) / 2**count)
