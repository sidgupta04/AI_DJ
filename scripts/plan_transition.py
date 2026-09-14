#!/usr/bin/env python3
"""Plan a transition from a given track.

Usage:
    uv run python scripts/plan_transition.py --track-id 42
    uv run python scripts/plan_transition.py --track-id 42 --session-bpm 126
    uv run python scripts/plan_transition.py --track-id 42 --played 10,20,30
"""

from __future__ import annotations

import argparse
import sys

from autodj.config.settings import load_settings
from autodj.logging_config import configure_logging
from autodj.persistence.database import build_engine, build_session_factory
from autodj.services.selection import SelectionService


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Plan a transition from a given track")
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
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_format)

    played_ids: set[int] = set()
    if args.played:
        played_ids = {int(x.strip()) for x in args.played.split(",") if x.strip()}

    engine = build_engine(settings)
    session_factory = build_session_factory(engine)

    service = SelectionService(settings, session_factory)

    try:
        result = service.select_next(
            args.track_id,
            played_ids,
            session_bpm=args.session_bpm,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    current = result.current_track
    print(f"\nCurrent track: [{current.track_id}] {current.audio_path}")
    print(f"  BPM: {current.native_bpm:.2f}  Energy: {current.energy:.3f}")
    print(f"  Session BPM: {args.session_bpm or current.native_bpm:.2f}")
    if result.relaxed:
        print("  (energy filter relaxed)")

    print(f"\nCandidates retrieved: {len(result.ranked)}")
    if not result.ranked:
        print("  No compatible tracks found.")
        sys.exit(0)

    print("\nTop 5 ranked candidates:")
    for i, ranked in enumerate(result.ranked[:5]):
        c = ranked.candidate
        print(
            f"  {i + 1}. [{c.track_id}] {c.audio_path}"
            f"  BPM={c.native_bpm:.2f}  E={c.energy:.3f}"
            f"  cost={ranked.total_cost:.4f}"
            f"  (tempo={ranked.tempo_cost:.3f} energy={ranked.energy_cost:.3f}"
            f" quality={ranked.quality_cost:.3f})"
        )

    if result.plan is not None:
        plan = result.plan
        print("\nTransition plan:")
        print(f"  Track A [{plan.track_a_id}] → Track B [{plan.track_b_id}]")
        print(f"  Stretch ratio: {plan.stretch_ratio:.4f}")
        print(
            f"  Outgoing region: beats {plan.outgoing_region.start_beat}"
            f"–{plan.outgoing_region.end_beat}"
            f" ({plan.outgoing_region.start_time:.2f}s–{plan.outgoing_region.end_time:.2f}s)"
        )
        print(
            f"  Incoming region: beats {plan.incoming_region.start_beat}"
            f"–{plan.incoming_region.end_beat}"
            f" ({plan.incoming_region.start_time:.2f}s–{plan.incoming_region.end_time:.2f}s)"
        )
        print(
            f"  Pair cost: {plan.pair_cost:.4f}"
            f"  (stability={plan.stability_cost:.3f}"
            f" energy={plan.energy_cost:.3f}"
            f" stretch={plan.stretch_cost:.3f}"
            f" position={plan.position_cost:.3f})"
        )
    else:
        print("\n  No valid transition plan found (no qualifying region pairs).")


if __name__ == "__main__":
    main()
