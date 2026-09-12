"""Ingest an audio library into the tracks table.

Usage:
    uv run python scripts/ingest_library.py [--library-dir PATH] [--recheck] [--dry-run]

Source files are only ever read. Nothing here modifies the library.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autodj.config.settings import load_settings
from autodj.logging_config import configure_logging
from autodj.persistence.database import build_engine, build_session_factory
from autodj.services.ingestion import LibraryIngestionService


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
        "--recheck",
        action="store_true",
        help="re-probe and re-validate files whose contents have not changed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show how each file's title and artist would be resolved, without writing rows",
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

    service = LibraryIngestionService(settings, build_session_factory(build_engine(settings)))

    try:
        if args.dry_run:
            return _print_preview(service, args.library_dir)
        report = service.scan(args.library_dir, recheck=args.recheck)
    except NotADirectoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        f"scanned={report.scanned} added={report.added} updated={report.updated} "
        f"unchanged={report.unchanged} failed={report.failed} "
        f"elapsed={report.elapsed_seconds:.2f}s"
    )
    for audio_path, reason in report.failures:
        print(f"  FAILED {reason}: {audio_path}")
    return 0


def _print_preview(service: LibraryIngestionService, library_dir: Path | None) -> int:
    previews = service.preview(library_dir)
    for preview in previews:
        if preview.failure is not None:
            print(f"  FAILED {preview.failure['reason']}: {preview.audio_path}")
            continue
        naming = preview.naming
        if naming is None:
            continue
        artist = naming.artist or "-"
        print(f"  [{naming.source:8}] {artist} :: {naming.title}  <- {preview.audio_path}")
    print(f"previewed={len(previews)} files (no rows written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
