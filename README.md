# AutoDJ

An automated DJ engine. It analyzes an audio library offline (BPM, beat grid, energy, stable
rhythmic regions), ranks candidate next tracks with a weighted tempo/energy compatibility model,
picks transition points inside detected stable regions, time- and phase-aligns beat grids, and
renders equal-power crossfades while recording latency and transition-quality metrics.

V1 targets a controlled library of roughly 100 house/electronic tracks in steady 4/4.

**Status: Milestone 2 of 9 — BPM and beat-grid analysis (complete).** Ingested tracks can be
decoded and analysed offline into a native BPM, a refined beat grid, and a documented
quality score. Energy analysis, transition planning, and mixing are not started. The
authoritative plan is `docs/roadmap.md`; see `AGENTS.md` for the one-milestone-per-run
working agreement.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- ffmpeg and ffprobe on `PATH` (audio decoding)
- Docker (only to run the PostgreSQL container)

## Setup

```bash
uv sync                     # create .venv and install dependencies
cp .env.example .env        # adjust paths and credentials
docker compose up -d        # PostgreSQL 16 on localhost:5432
uv run alembic upgrade head # apply migrations
```

Run the API:

```bash
uv run uvicorn autodj.api.app:create_app --factory --reload
curl -s localhost:8000/health
```

## Ingesting a library

```bash
uv run python scripts/ingest_library.py --dry-run    # preview names, write nothing
uv run python scripts/ingest_library.py              # scan and persist
uv run python scripts/ingest_library.py --recheck    # revalidate unchanged files too
```

The scan reads `AUTODJ_AUDIO_LIBRARY_DIR` (override with `--library-dir`), hashes each file,
probes it with ffprobe, validates a short decoded window, and records a `tracks` row awaiting
analysis. Filenames are treated as source paths, not as a naming convention: embedded tags are
preferred, and a sanitized filename is only a fallback. Unreadable, too-short, or entirely silent
files are recorded as failures with a structured reason instead of aborting the scan; a track that
merely *starts* silent is kept.

A track is identified by its library-relative path, so rescanning is idempotent and editing a file
in place re-validates it. `content_hash` only detects those changes — it never merges rows, so the
same audio at two paths is two tracks. See `docs/architecture.md`.

## Analysing beats

```bash
uv run python scripts/analyze_library.py                 # pending and stale-version rows
uv run python scripts/analyze_library.py --reanalyze     # also redo COMPLETE and FAILED
uv run python scripts/analyze_library.py --path "a.mp3"  # one already-ingested path
uv run python scripts/analyze_library.py --limit 10
```

Each pending track is decoded to mono PCM at `analysis.sample_rate` and run through librosa
beat tracking, octave disambiguation, and sub-frame refinement. `native_bpm`,
`analysis_confidence` and `analysis_version` are stored on `tracks`; the beat timestamps and
diagnostics go in `track_analysis`. `analysis_confidence` is a heuristic beat-grid quality
score in [0, 1] (regularity × onset alignment), not a probability that the BPM is correct.
Unreliable grids are recorded as `FAILED` with a structured reason and never invent a BPM.
See `docs/algorithms.md`.

The 22.05 kHz default was compared with 44.1 kHz on synthetic click tracks before being treated
as settled; the numbers are in `docs/experiments.md`.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports          # enforces the layering contracts
uv run pytest
```

## Layout

```text
backend/autodj/
  audio/        pure DSP: decode, beats, energy, stable regions
  dj/           pure decisions: retrieval, ranking, transition planning
  render/       time stretch, beat alignment, crossfade, mix rendering
  metrics/      transition quality and latency measurement
  persistence/  SQLAlchemy models, repositories, Alembic migrations
  services/     orchestration; the only layer that composes the others
  api/          FastAPI routes
  config/       settings.py and default.yaml (every tunable, with reasons)
backend/tests/  unit and integration tests, synthetic audio only
docs/           roadmap, architecture, algorithms, parameters, experiments, evaluation, licensing
```

`audio/` and `dj/` are pure: no database, no HTTP. This is enforced by import-linter contracts in
`pyproject.toml`. `audio/decode.py` is the one deliberate exception, since ffmpeg and ffprobe read
files from disk; keeping that boundary in a single module leaves the rest of the DSP code testable
on arrays alone.

## Audio library

Source audio is never committed. Point `AUTODJ_AUDIO_LIBRARY_DIR` at a local folder of MP3s;
AutoDJ treats those files as read-only inputs and writes generated audio to
`AUTODJ_RENDER_CACHE_DIR`. Automated tests use synthetic audio and never need the library.

## Configuration

All experimental parameters live in `backend/autodj/config/default.yaml`, each with a reason.
Environment variables override them (`AUTODJ_` prefix, `__` for nested keys, e.g.
`AUTODJ_ANALYSIS__SAMPLE_RATE=44100`). Defaults and their experiment history are documented in
`docs/parameters.md`.

## License

GPLv3, because the default pitch-preserving time stretcher links Rubber Band via `pedalboard`.
See `docs/licensing.md` for the dependency license inventory and how to swap the DSP backend.
