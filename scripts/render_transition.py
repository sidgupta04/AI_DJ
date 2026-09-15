#!/usr/bin/env python3
"""Plan and render a transition from a given track.

Usage:
    uv run python scripts/render_transition.py --track-id 42
    uv run python scripts/render_transition.py --track-id 42 --session-bpm 126
    uv run python scripts/render_transition.py --track-id 42 --output /tmp/mix.wav
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autodj.config.settings import load_settings
from autodj.logging_config import configure_logging
from autodj.persistence.database import build_engine, build_session_factory
from autodj.persistence.models import TransitionStatus
from autodj.services.render import RenderService
from autodj.services.selection import SelectionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan and render a transition from a given track")
    parser.add_argument("--track-id", type=int, required=True, help="ID of the current track")
    parser.add_argument(
        "--session-bpm",
        type=float,
        default=None,
        help="Session BPM (defaults to the current track's native BPM)",
    )
    parser.add_argument(
        "--played",
        type=str,
        default="",
        help="Comma-separated IDs of already-played tracks",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="WAV destination (defaults to AUTODJ_RENDER_CACHE_DIR/transitions/...)",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_format)
    session_factory = build_session_factory(build_engine(settings))

    played_ids: set[int] = set()
    if args.played:
        played_ids = {int(x.strip()) for x in args.played.split(",") if x.strip()}

    selection = SelectionService(settings, session_factory)
    try:
        result = selection.select_next(
            args.track_id,
            played_ids,
            session_bpm=args.session_bpm,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.plan is None:
        print("No valid transition plan found (no qualifying region pairs).", file=sys.stderr)
        return 1

    plan = result.plan
    print(f"Plan: track {plan.track_a_id} → {plan.track_b_id}  stretch={plan.stretch_ratio:.4f}")
    print(
        f"  outgoing beats {plan.outgoing_region.start_beat}–{plan.outgoing_region.end_beat}"
        f"  incoming beats {plan.incoming_region.start_beat}–{plan.incoming_region.end_beat}"
    )

    rendered = RenderService(settings, session_factory).render_plan(plan, output_path=args.output)
    if rendered.status is TransitionStatus.FAILED:
        failure = rendered.failure or {}
        print(
            f"Render failed ({failure.get('reason')}): {failure.get('detail')}",
            file=sys.stderr,
        )
        return 1

    print(f"Wrote {rendered.wav_path}")
    print(
        f"  peak_dbfs={rendered.peak_dbfs:.2f}"
        f"  peak_exceeded={rendered.peak_exceeded}"
        f"  clipped={rendered.clipped}"
        f"  transition_id={rendered.transition_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
