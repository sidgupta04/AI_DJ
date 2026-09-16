# Licensing

AutoDJ is distributed under **GPLv3** (see `LICENSE`).

## Why GPLv3

The default pitch-preserving time stretcher is the [Rubber Band
Library](https://breakfastquay.com/rubberband/), reached through
[`pedalboard`](https://github.com/spotify/pedalboard). Rubber Band is dual-licensed commercially
and under GPLv2-or-later, and `pedalboard` itself is GPLv3, so a project that links it is a
GPLv3 work. This was a deliberate trade: Rubber Band is the best-quality pitch-preserving stretch
available from Python without a commercial license, and transition quality is the point of the
project.

## Consequences

- Source must stay available under GPLv3 for anyone who receives a distributed build.
- Closed-source or commercial redistribution requires either a commercial Rubber Band license or
  swapping the DSP backend.

## Swapping the stretch backend

`tempo.stretch_backend` selects the implementation behind the `TimeStretcher` interface.
Only `pedalboard` is implemented in M5:

| Backend | Library | License | Notes |
| --- | --- | --- | --- |
| `pedalboard` | `pedalboard` (Rubber Band) | GPLv3 | Default. Best quality, pip wheels, stereo float32. |
| `rubberband_cli` | `pyrubberband` + `rubberband` CLI | GPLv2+ | Same engine as a subprocess; needs a system package. Not implemented. |
| `phase_vocoder` | `librosa` | ISC | Permissive fallback; audibly worse at larger ratios. Not implemented. |

Choosing `phase_vocoder` and removing the `pedalboard` dependency is what a permissive relicensing
would require. Keep that path documented.

## Third-party licenses in use

| Dependency | License | Role |
| --- | --- | --- |
| FastAPI, Starlette, uvicorn | MIT / BSD | HTTP layer |
| pydantic, pydantic-settings | MIT | Configuration and schemas |
| SQLAlchemy, Alembic | MIT | Persistence and migrations |
| psycopg | LGPL-3.0 | PostgreSQL driver (dynamically linked, no additional obligation here) |
| structlog | MIT / Apache-2.0 | Structured logging |
| ffmpeg (external binary) | LGPL/GPL depending on build | Decoding, invoked as a subprocess |
| librosa | ISC | Offline onset envelope and dynamic-programming beat tracking |
| pedalboard | GPLv3 | Pitch-preserving time stretch (Rubber Band) |

`librosa` is the beat tracker specified for M2. It is permissive (ISC) and does not change
the project's GPLv3 obligation, which comes from Rubber Band / `pedalboard`.
It pulls a scientific Python stack (numpy, scipy, numba, scikit-learn, soundfile, soxr)
under BSD/MIT-style licenses.

Adding a dependency means adding it here with its license and role.

M7 frontend additions: React/React DOM (MIT) provide the required one-screen interactive UI;
Vite (MIT) builds it and proxies the local API. Manrope (SIL Open Font License 1.1), packaged
by Fontsource, supplies locally hosted typography without remote font requests. Vitest (MIT),
Testing Library (MIT), jsdom (MIT), and Prettier (MIT) are development-only test/format tools.
The exact dependency graph is locked in `frontend/package-lock.json`; no Python DSP dependency
or project license changed.
