"""Analyse ingested tracks: BPM, beat grid, and analysis confidence.

Usage:
    uv run python scripts/analyze_library.py
    uv run python scripts/analyze_library.py --reanalyze
    uv run python scripts/analyze_library.py --path "House/track.mp3"
    uv run python scripts/analyze_library.py --limit 10

Source files are only ever read. Nothing here modifies the library.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autodj.config.settings import load_settings
from autodj.logging_config import configure_logging
from autodj.persistence.database import build_engine, build_session_factory
from autodj.services.analysis import LibraryAnalysisService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=None,
        help="override the configured audio library directory",
    )
    parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="redo COMPLETE and FAILED tracks, not only the pending queue",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="analyse a single library-relative path already present in the tracks table",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="analyse at most this many tracks, in path order",
    )
    parser.add_argument("--log-level", default=None, help="override the configured log level")
    parser.add_argument(
        "--log-format", default=None, choices=["console", "json"], help="override the log format"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    configure_logging(args.log_level or settings.log_level, args.log_format or settings.log_format)

    service = LibraryAnalysisService(settings, build_session_factory(build_engine(settings)))

    try:
        report = service.analyze(
            args.library_dir,
            reanalyze=args.reanalyze,
            audio_path=args.path,
            limit=args.limit,
        )
    except NotADirectoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        f"selected={report.selected} completed={report.completed} failed={report.failed} "
        f"skipped={report.skipped} elapsed={report.elapsed_seconds:.2f}s"
    )
    for audio_path, reason in report.failures:
        print(f"  FAILED {reason}: {audio_path}")
    if args.path is not None and report.selected == 0:
        print(f"error: no track row for {args.path}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
