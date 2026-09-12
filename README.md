# AutoDJ

An automated DJ engine. It analyzes an audio library offline (BPM, beat grid, energy, stable
rhythmic regions), ranks candidate next tracks with a weighted tempo/energy compatibility model,
picks transition points inside detected stable regions, time- and phase-aligns beat grids, and
renders equal-power crossfades while recording latency and transition-quality metrics.

V1 targets a controlled library of roughly 100 house/electronic tracks in steady 4/4.

**Status: Milestone 1 of 16 — audio ingestion.** The library can be scanned into PostgreSQL; no
beat detection or mixing behavior exists yet. Milestones are implemented one at a time; see
`AGENTS.md` for the working agreement.

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
docs/           architecture, algorithms, parameters, experiments, evaluation, licensing
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
