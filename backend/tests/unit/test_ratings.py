from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from autodj.services.evaluation_tools import analyze_ratings


def test_listeners_are_aggregated_per_pair_before_sign_test(tmp_path: Path) -> None:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"p1": {"X": "D", "Y": "B"}, "p2": {"X": "B", "Y": "D"}}))
    ratings = tmp_path / "ratings.csv"
    columns = [
        "pair_id",
        "listener_id",
        "preference",
        "smoothness_X",
        "smoothness_Y",
        "rhythm_X",
        "rhythm_Y",
        "energy_X",
        "energy_Y",
    ]
    with ratings.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for pair in ("p1", "p2"):
            for listener in range(3):
                writer.writerow(
                    {
                        **{name: 4 for name in columns},
                        "pair_id": pair,
                        "listener_id": str(listener),
                        "preference": "X" if pair == "p1" else "Y",
                    }
                )
    result = analyze_ratings(ratings, key, minimum_listeners=3)
    assert result["D_wins"] == 2  # not six independent votes
    assert result["two_sided_sign_test_p"] == 0.5
    assert result["eligible_pairs"] == 2
    assert analyze_ratings(ratings, key, minimum_listeners=4)["two_sided_sign_test_p"] is None
    with ratings.open("a") as handle:
        handle.write("p1,0,X,4,4,4,4,4,4\n")
    with pytest.raises(ValueError, match="duplicate"):
        analyze_ratings(ratings, key, minimum_listeners=3)
