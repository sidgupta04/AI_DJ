# AutoDJ

An automated DJ engine. It analyzes an audio library offline (BPM, beat grid, energy, stable
rhythmic regions), ranks candidate next tracks with a weighted tempo/energy compatibility model,
picks transition points inside detected stable regions, time- and phase-aligns beat grids, and
renders equal-power crossfades while recording latency and transition-quality metrics.

V1 targets a controlled library of roughly 100 house/electronic tracks in steady 4/4.

**Status: Milestone 0 of 16 — project skeleton.** No audio analysis or mixing behavior exists yet.
Milestones are implemented one at a time; see `AGENTS.md` for the working agreement.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- ffmpeg and ffprobe on `PATH` (audio decoding, used from M1)
- Docker (only to run the PostgreSQL container)

## Setup

```bash
uv sync                     # create .venv and install dependencies
cp .env.example .env        # adjust paths and credentials
docker compose up -d        # PostgreSQL 16 on localhost:5432
uv run alembic upgrade head # apply migrations (none yet at M0)
```

Run the API:

```bash
uv run uvicorn autodj.api.app:create_app --factory --reload
curl -s localhost:8000/health
```

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

`audio/` and `dj/` are pure: no database, no HTTP, no filesystem. This is enforced by
import-linter contracts in `pyproject.toml`.

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
