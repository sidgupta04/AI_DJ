# Evaluation

A working demo is not evidence. Each added piece of the algorithm must be shown to help, or shown
not to.

## Model ladder

Every implemented model is a selectable strategy so results are reproducible from a config snapshot and a seed
track.

- Baseline A — random next track.
- Baseline B — nearest BPM, fixed crossfade near the track edge.
- Model C — BPM + energy compatibility ranking.
- Model D — C plus stable-region transition selection and beat alignment.
- Model E — D plus bounded lookahead sequencing (M6 stretch only, if greedy fails).

## Objective metrics

Recorded per transition (see the `transitions` table) and reported as distributions, not averages:

- native BPM delta and stretch percentage;
- measured beat-alignment error in ms, from onset-envelope cross-correlation of the two stems
  inside the overlap, not from the planned arithmetic;
- local energy discontinuity across the transition;
- chosen region stability scores;
- transition success and failure rates by failure type;
- planning and render latency (p50/p95/p99), plus offline analysis duration and failure rate.

## Human evaluation (M6)

60 transition pairs, baseline B versus model D on identical track pairs, presented blind and
order-randomized to at least three listeners. Ratings: smoothness, rhythmic coherence, and energy
continuity on 1-5 scales, plus an overall A/B preference. Analyzed with a paired sign test and
reported alongside the config snapshot that produced the audio.

## Results

The first recorded result is the M2 analysis sample-rate comparison (synthetic click tracks,
22.05 kHz vs 44.1 kHz, hop length held at 512). It lives in `docs/experiments.md` because it
answers a configuration question rather than a transition-quality question. M6 transition-level
results and their reproduction commands follow below.

## Running the M6 tooling

Apply the M6 Alembic migration before using database-backed evaluation. Existing M5 rows keep
null evaluation columns; existing WAVs have not magically acquired measurements. New evaluations
use unique run directories and insert separate `transitions` rows. The ordinary M5 render CLI
remains usable and does not perform expensive evaluation on the runtime path.

```bash
uv run alembic upgrade head
uv run python scripts/evaluate_library.py --output render_cache/eval-001 --analyze
uv run python scripts/evaluate_library.py --output render_cache/eval-002 --track-ids 1,2,3 --seed 42 --pair-count 60 --strategies B D
uv run python scripts/experiment_evaluation.py --output render_cache/m6-synthetic-20260915-final
```

The first command evaluates pending/stale offline analysis jobs and records batch duration,
completed/failed/skipped counts, failure rate and reason counts. Without `--analyze`, historical
analysis duration/failure rate is unavailable (`null`): ingestion and analysis share FAILED
status, so an inventory count cannot honestly reconstruct an analysis-run failure rate.
The synthetic experiment plants known beat grids and region scores to isolate M4/M5;
it does not benchmark offline feature extraction. Integration tests cover real analysis.

The ladder evaluates each requested current track once under each selected strategy. A uses
`seed + current-track index`; repeat with other seeds to study random-selection variability.
All baselines stay inside the hard stretch bound. B/D blind candidates are seeded, unique
ordered track pairs within that bound; at most `pair_count` are attempted. Failures are retained,
not replaced with easier pairs. The exporter reports requested, attempted, exported and shortfall
counts instead of duplicating audio to pretend it reached 60 pairs.

Outputs:

- `report.json`: raw attempts, metric distributions, failure reasons, configuration (without
  database credentials), random seed, package versions, implementation fingerprint, source
  content hashes and the complete candidate feature snapshot.
- `ladder/` and `paired/`: administrator WAVs for independent next-track comparisons and fixed
  B/D track-pair comparisons respectively.
- `blind/participants/`: generic `pair_NNN_X.wav` / `Y.wav`, instructions and empty `ratings.csv`
  rows for three listeners. Share only this directory with listeners.
- `blind/codebook.json`: administrator-only model assignment and track IDs. Keep separate.

X/Y order is randomized reproducibly per pair. Each pair has identical fade duration and
matching before/after context: up to `excerpt_seconds`, shortened on both versions when either
source lacks that context. No extra loudness normalization is applied; amplitude differences
are part of energy-continuity evaluation. No listener scores are generated automatically.

After the owner collects ratings:

```bash
uv run python scripts/analyze_ratings.py --ratings render_cache/eval-001/blind/participants/ratings.csv --codebook render_cache/eval-001/blind/codebook.json
```

Incomplete ratings, invalid scales, unknown pairs and duplicate listener/pair records are
rejected. Preference statistics aggregate listeners by audio pair before applying the sign
test; fewer than three complete listener ratings exclude a pair. See `docs/algorithms.md`
for exact formulas, units, missing-data handling and statistical limits.

## M6 synthetic result — 2026-09-15

Four 80-second stereo click tracks: BPM 120/121/124/138, phase 0/120/230/310 ms,
amplitude 0.2/0.2/0.55/0.2; planted exact beat grids and two stable windows per track.
Configuration: default.yaml, evaluation seed 20260915; only source path overridden.
The 138 BPM track deliberately has no compatible next track. Full reproducible details are
recorded in `docs/experiments.md`.

| Strategy | Rendered / attempted | Native BPM delta p50 | Alignment ms p50 / p95 (measured n) | Energy gap dB p50 / p95 |
| --- | --- | ---: | --- | --- |
| A | 3 / 4 | 3 | 64.9 / 64.9 (1) | 8.40 / 9.24 |
| B | 3 / 4 | 1 | 64.9 / 109.8 (3) | 0.77 / 8.48 |
| C | 3 / 4 | 1 | 64.9 / 109.8 (3) | 0.77 / 8.48 |
| D | 3 / 4 | 1 | 5.0 / 9.5 (3) | 2.62 / 10.24 |

Every strategy had one `NO_PLAN` failure (25%). A additionally had two weak-correlation
overlaps with unavailable alignment; they were not counted as zero. C and B chose the same
tracks on this small dataset, so this experiment does not demonstrate an energy-ranking gain.

Fixed B/D comparison: six identical ordered pairs, all rendered successfully and exported
blind (54-pair shortfall against 60). B alignment p50/p95 was 57.4/107.3 ms over four measurable
pairs; D was 10.0/15.0 ms over six. Energy gap p50/p95 was B 8.38/9.38 dB versus D 7.30/11.12 dB.
Different valid-alignment counts mean the two alignment distributions are not a complete paired
effect estimate. The raw report retains per-pair measurements for inspection.

On the final local run, paired planning p50/p95/p99 was B 0.061/0.166/0.192 ms and
D 0.101/0.148/0.153 ms. Render p50/p95/p99 was B 3.394/3.571/3.595 seconds and
D 3.424/3.476/3.482 seconds. These tiny-sample timings include cold/warm order and local load;
they are descriptive, not a production performance claim. Measurement cost was approximately
0.012 seconds at the median. Region scores for D were planted 1.0, not validation of M3.

Conclusion: this fixture supports measured phase improvement but not consistent energy
improvement. No production algorithm defaults changed and no beam search was added.
That experiment used `analysis.version` 2. The subsequent approved octave-policy change
first bumped the current version to 3; the subsequent real-audio confidence calibration bumps it
to 4. These planted-grid results remain historical.
Real-library comparisons and owner-run listening remain outstanding;
the blind tooling, not completed listener recruitment, is M6's merge gate.

Validation: all 220 tests passed (no skips), including new known-offset, baseline, rating,
failure-cleanup, end-to-end database evaluation and historical-migration coverage. Ruff lint,
Ruff format check, mypy and all three import-linter contracts passed. Two existing
FastAPI/Starlette deprecation warnings remain. No dependency was added.
