# Experiments

One entry per experiment, newest first. An entry is only complete if another person could rerun it
from what is written here.

Template:

```text
## <date> — <question being answered>

Milestone:
Configuration: <config snapshot or the parameters that differ from default.yaml>
Dataset: <synthetic fixtures / library size / track selection>
Method: <what was run, which command>
Result: <numbers, distributions, not adjectives>
Decision: <what changed in default.yaml or the code, and why>
```

## 2026-09-16 — Does click-grid review justify changing the confidence acceptance floor?

Milestone: M6 follow-up; explicitly approved calibration of the existing acceptance threshold.
Configuration: `analysis.version: 4`, `max_ibi_cv: 0.12`, `min_onset_contrast: 0.15`,
`min_confidence: 0.225`. The formula remains `regularity × onset_contrast`; no scoring,
octave-selection, refinement, or individual gate changed.
Dataset: owner-run diagnostic output on seven commercial house/pop tracks. The generated click
WAV overlays the exact refined M2 timestamps on a decoded copy; source MP3s and diagnostic WAVs
are private and uncommitted.
Method: inspect `scripts/diagnose_beat_confidence.py --click-output-dir` exports, alongside
the diagnostic components and stable-region report. Compare candidate floors 0.15, 0.175, 0.20,
0.225, and 0.25 without changing the formula.
Result: Super Bass scored 0.236 (regularity 0.762, onset contrast 0.310), had eight stable
regions (best 0.912), and its click grid was nearly perfectly locked. It fails 0.25 but passes
0.225. Levels scored 0.181 and Shiver 0.101; click review found audible drift in weaker-onset
sections, so both remain rejected at 0.225. Lower floors would additionally admit Levels at
0.175 and Payphone (0.157) at 0.15. The individual regularity and onset gates remain in force.
Decision: lower only `analysis.min_confidence` from 0.25 to 0.225. This is the smallest tested
change that accepts the reviewed locked grid without admitting the audibly drifting examples.
Bump `analysis.version` from 3 to 4 so completed analyses are stale and reprocessed; FAILED
rows still require explicit retry. The sample is small and is a calibration checkpoint, not a
claim that the score is a probability or a reason to change its formula.

## 2026-09-15 — Best eligible octave after real-library range failures

Milestone: M6 follow-up; explicitly approved change to the M2 octave policy.
Owner-reported evidence: Losing It and Atmosphere selected global 246.09 BPM despite
123.05 alternatives; Bla Bla Bla selected global 304 BPM despite a 152 alternative.
Those failures matched the old policy. V1 now treats 80–180 BPM as candidate eligibility,
then maximizes the unchanged onset score; the 124 prior still breaks exact ties only.

Configuration: `analysis.version: 3`, `min_bpm: 80`, `max_bpm: 180`, `start_bpm: 124`.
All scoring, refinement and quality settings are unchanged (`max_ibi_cv: 0.12`,
`min_onset_contrast: 0.15`, `min_confidence: 0.25`).
Dataset: synthetic alternating 1.0/0.8 onset attacks at double tempo; 123.05/246.10
and 152/304 BPM, each with native and double-time raw grids. No private audio in tests.
Method: `uv run pytest backend/tests/unit/test_beats.py`.
Result: double time scores higher in all four cases, but selection returns 123.05 or 152.
An all-out-of-range 15/30/60 set still fails. The 62 BPM click fixture now selects about
124 and passes default gates; a stricter test-only confidence gate still rejects it.
Decision: adopt the approved policy and version bump. Completed version 1/2 rows become
stale and are automatically queued; FAILED rows need `--reanalyze` or an explicit `--path`.
The four real tracks were not reanalyzed here; eligible BPM does not guarantee that later
quality or stable-region gates pass. Earlier version-2 experiment snapshots remain historical.

## 2026-09-15 — Does full planning/alignment improve the model ladder on known synthetic grids?

Milestone: M6
Configuration: repository `default.yaml` at M6, no algorithm overrides; seed 20260915.
Runtime `audio_library_dir` points at generated sources. Snapshot and source hashes are in
`render_cache/m6-synthetic-20260915-final/comparison/report.json` (ignored generated artifacts).
Implementation SHA-256: `e96bbb2f467747b94a6fc0ecfc47ca1ae196fb698d6c56d21b5d3bd44b3f5703`.
Packages: AutoDJ 0.1.0, numpy 2.5.3, pedalboard 0.9.25, librosa 1.0.0.

```text
analysis.version: 2
tempo.min_stretch_ratio: 0.95
tempo.max_stretch_ratio: 1.05
tempo.stretch_backend: pedalboard
render.sample_rate: 44100
render.channels: 2
render.output_bit_depth: 16
render.peak_ceiling_dbfs: -1
ranking: {weight_tempo: 0.60, weight_energy: 0.35, weight_quality: 0.05}
retrieval: {energy_filter_enabled: true, max_energy_delta: 0.25, require_stable_region: true, allow_repeats: false}
transition: {crossfade_beats: 32, margin_beats: 8, outgoing_search_fraction: [0.65, 0.95], incoming_search_fraction: [0.0, 0.35], weight_stability: 0.40, weight_energy: 0.30, weight_stretch: 0.20, weight_position: 0.10, align_on_downbeat: true}
evaluation: {excerpt_seconds: 15, pair_count: 60, seed: 20260915, onset_hop_ms: 5, alignment_max_lag_ms: 200, alignment_min_correlation: 0.1, energy_window_seconds: 1, silence_floor_dbfs: -90, minimum_listeners: 3}
```

Dataset: four 80 s stereo exponential click trains at BPM 120/121/124/138, phase
0/0.12/0.23/0.31 s, amplitude 0.2/0.2/0.55/0.2. Click length 20 ms, decay constant 4 ms.
Beat times are exact; confidence and region scores are planted 1.0, IBI CV 0.0,
track/region energy is planted amplitude. Windows start at beat 8 and the four-beat-rounded
70% beat index and span 32 timestamps. This is a controlled render/selection experiment,
not an offline-analyzer benchmark or realistic music model.

Method: `uv run python scripts/experiment_evaluation.py --output render_cache/m6-synthetic-20260915-final`.
Use a new output path for a rerun. A–D each attempt one next-track decision for every current
track; B/D additionally render the six unique ordered tempo-compatible pairs. No manual audio
selection or listener ratings. The code writes generic X/Y excerpts and an empty rating sheet.

Result: every ladder strategy 3/4 success, one NO_PLAN due to isolated 138 BPM track. B and C
selected identical successors. Ladder alignment median: A 64.9 ms (1 measurable), B/C 64.9 ms
(3), D 5.0 ms (3). Fixed B/D median/p95: B 57.4/107.3 ms (4 of 6 measurable), D 10.0/15.0 ms
(6 of 6). B's two remaining overlaps had weak correlation, not a measured zero. Fixed-pair
energy discontinuity median/p95: B 8.38/9.38 dB, D 7.30/11.12 dB. All six pairs exported;
54-pair shortfall is explicit. Timing distributions and full ladder table: `docs/evaluation.md`.

Decision: keep all production ranking, planning, analysis and rendering defaults. Alignment
improves this controlled case, while energy and musical preference are not established.
No observed set-level greedy failure justifies lookahead; no session sequencing is implemented.
Analysis version stays 2; no reprocessing. Owner follows up with real-library evaluation and
at least three listeners on a sufficiently large, diverse set of pairs.

## 2026-09-14 — Do the default region gates keep a tight grid and reject a sparse or wandering one?

Milestone: M3
Configuration: `default.yaml` `stable_regions` section

```text
stable_regions.window_beats: 32
stable_regions.step_beats: 4
stable_regions.ibi_cv_max: 0.06
stable_regions.ibi_tolerance: 0.05
stable_regions.in_tolerance_fraction_min: 0.90
stable_regions.onset_strength_floor: 0.35
stable_regions.max_regions_per_track: 8
```

Dataset: synthetic 48-beat grids at 124 BPM, generated in memory. No private library.
Jitter is uniform time noise as a fraction of the nominal IBI, then sorted.
Method: `uv run python scripts/experiment_region_thresholds.py`

Result:

| grid | IBI CV | detect (onset=1.0) |
| --- | ---: | --- |
| perfect | 0.0000 | PASS n=1 score=1.000 |
| 2% jitter | 0.0165 | PASS n=1 score=0.875 cv=0.0150 |
| 5% jitter | 0.0445 | FAIL `NO_STABLE_REGION` (in-tolerance gate) |
| 8% jitter | 0.0760 | FAIL `NO_STABLE_REGION` (CV > 0.06) |
| perfect, onset=0.05 | 0.0000 | FAIL `NO_STABLE_REGION` (onset floor) |

Decision: keep `ibi_cv_max = 0.06` and `onset_strength_floor = 0.35`. 2% jitter matches the
tight house CV cited in `default.yaml` (0.01–0.02) and still mixes. 5% jitter is already
rejected by the 90%-within-5% in-tolerance gate, so CV is not the only brake. The onset
floor still refuses a metronomic but pulse-less grid.

## 2026-09-14 — Does median energy resist a loud intro/outro better than mean or p90?

Milestone: M3
Configuration: `default.yaml` energy section (`alpha` 0.6, dBFS window −60/0, curve 10 Hz,
onset percentiles 5/95). Aggregation is the independent variable.

Dataset: one 24 s, 124 BPM pulsed 220 Hz tone (50% duty, body amplitude 0.15) versus the
same loop with a 2 s full-scale sine intro and outro. Generated in memory. No private
library.
Method: `uv run python scripts/experiment_energy_aggregation.py`

Result:

| method | body | spiked | delta |
| --- | ---: | ---: | ---: |
| median | 0.3914 | 0.4047 | +0.0133 |
| mean | 0.2729 | 0.3248 | +0.0519 |
| p90 | 0.4582 | 0.5704 | +0.1122 |

Decision: keep `energy.aggregation = median`. The loud edges move median by 0.013 and mean
by 0.052; p90 tracks the spike. Revisit only if real-library drops turn out to be quieter
than the body rather than louder.

## 2026-09-12 — Does analysing at 44.1 kHz improve BPM or beat timing enough to drop 22.05 kHz?

Milestone: M2
Configuration: `default.yaml` analysis section, hop length held at 512 for both rates

```text
analysis.version: 1
analysis.hop_length: 512
analysis.refine_hop_length: 256
analysis.start_bpm: 124
analysis.min_bpm: 80
analysis.max_bpm: 180
analysis.min_beats: 16
analysis.max_ibi_cv: 0.12
analysis.min_onset_contrast: 0.15
analysis.min_confidence: 0.25
analysis.refine_search_radius_frames: 2
```

Dataset: five synthetic 16 s click tracks (decaying impulses on every beat) at 100, 120, 124,
128 and 140 BPM, generated in memory. No private library.
Method: `uv run python scripts/experiment_analysis_sample_rate.py` after a single librosa
warmup call. Each clip is analysed at 22050 Hz and 44100 Hz with the same hop lengths, so
44.1 kHz has a 2× finer onset grid (11.6 ms vs 23.2 ms coarse; 5.8 ms vs 11.6 ms refined).

Result:

| sr | true BPM | measured | bpm error | MAE ms | p95 ms | sec |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 22050 | 100 | 99.76 | −0.24 | 14.90 | 13.53 | 0.036 |
| 22050 | 120 | 120.08 | +0.08 | 11.04 | 13.49 | 0.035 |
| 22050 | 124 | 123.62 | −0.38 | 11.04 | 13.52 | 0.036 |
| 22050 | 128 | 128.21 | +0.21 | 10.98 | 13.48 | 0.038 |
| 22050 | 140 | 139.86 | −0.14 | 11.14 | 13.53 | 0.035 |
| 44100 | 100 | 100.11 | +0.11 | 9.04 | 6.66 | 0.091 |
| 44100 | 120 | 120.09 | +0.09 | 5.38 | 6.63 | 0.088 |
| 44100 | 124 | 124.14 | +0.14 | 5.36 | 6.65 | 0.082 |
| 44100 | 128 | 127.88 | −0.12 | 5.46 | 6.30 | 0.089 |
| 44100 | 140 | 139.84 | −0.16 | 5.41 | 6.66 | 0.083 |

| sr | mean \|bpm error\| | mean MAE ms | mean sec |
| ---: | ---: | ---: | ---: |
| 22050 | 0.210 | 11.82 | 0.036 |
| 44100 | 0.126 | 6.13 | 0.086 |

Decision: keep `analysis.sample_rate = 22050`. BPM, the number retrieval will filter on, is
already inside 0.4 BPM at 22.05 kHz. 44.1 kHz roughly halves timing error (as expected from a
finer hop in seconds) and costs ~2.4× wall time, which is not worth it for a tempo that later
alignment can still nudge. Revisit if measured mix alignment error in M5 is dominated by this
~12 ms residual.
