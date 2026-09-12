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

`tempo.stretch_backend` selects the implementation behind the `TimeStretcher` interface
(introduced in M6). Planned options:

| Backend | Library | License | Notes |
| --- | --- | --- | --- |
| `pedalboard` | `pedalboard` (Rubber Band) | GPLv3 | Default. Best quality, pip wheels, stereo float32. |
| `rubberband_cli` | `pyrubberband` + `rubberband` CLI | GPLv2+ | Same engine as a subprocess; needs a system package. |
| `phase_vocoder` | `librosa` | ISC | Permissive fallback; audibly worse at larger ratios. Kept as the comparison baseline in the M6 quality experiment. |

Choosing `phase_vocoder` and removing the `pedalboard` dependency is what a permissive relicensing
would require. Keep that path working.

## Third-party licenses in use

| Dependency | License | Role |
| --- | --- | --- |
| FastAPI, Starlette, uvicorn | MIT / BSD | HTTP layer |
| pydantic, pydantic-settings | MIT | Configuration and schemas |
| SQLAlchemy, Alembic | MIT | Persistence and migrations |
| psycopg | LGPL-3.0 | PostgreSQL driver (dynamically linked, no additional obligation here) |
| structlog | MIT / Apache-2.0 | Structured logging |
| ffmpeg (external binary) | LGPL/GPL depending on build | Decoding, invoked as a subprocess |

Adding a dependency means adding it here with its license and role.
