#!/usr/bin/env python3
"""Compare A–D and export blind B/D pairs from an analyzed library. No session loop."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from autodj.config.settings import load_settings
from autodj.dj.baselines import Strategy
from autodj.persistence.database import build_engine, build_session_factory
from autodj.services.analysis import LibraryAnalysisService
from autodj.services.evaluation import EvaluationService
from autodj.services.evaluation_tools import comparison_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New run directory; never overwritten"
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--pair-count", type=int)
    parser.add_argument("--strategies", nargs="+", choices=list(Strategy), default=list(Strategy))
    parser.add_argument(
        "--track-ids", help="Comma-separated IDs; default all current COMPLETE tracks"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run pending/stale analysis and record its duration/failures",
    )
    args = parser.parse_args()
    settings = load_settings()
    payload = settings.model_dump()
    for name in ("seed", "pair_count"):
        if getattr(args, name) is not None:
            payload["evaluation"][name] = getattr(args, name)
    settings = type(settings).model_validate(payload)
    if args.output.exists():
        parser.error("output directory already exists")
    engine = build_engine(settings)
    try:
        factory = build_session_factory(engine)
        offline = None
        if args.analyze:
            analysis = LibraryAnalysisService(settings, factory).analyze()
            attempted = analysis.completed + analysis.failed
            offline = {
                **asdict(analysis),
                "attempted": attempted,
                "failure_rate": analysis.failed / attempted if attempted else None,
                "failures_by_reason": dict(Counter(reason for _, reason in analysis.failures)),
            }
        service = EvaluationService(settings, factory)
        candidates = service.load_candidates()
        if args.track_ids:
            ids = {int(value) for value in args.track_ids.split(",")}
            candidates = [track for track in candidates if track.track_id in ids]
            if {track.track_id for track in candidates} != ids:
                parser.error("every requested ID must be a COMPLETE current-version candidate")
        if len(candidates) < 2:
            parser.error("at least two analyzed candidates are required")
        report = comparison_run(
            service,
            candidates,
            args.output,
            offline_analysis=offline,
            strategies=tuple(dict.fromkeys(Strategy(value) for value in args.strategies)),
        )
        print(
            json.dumps(
                {"ladder": report["ladder_summary"], "blind": report["blind_export"]}, indent=2
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
