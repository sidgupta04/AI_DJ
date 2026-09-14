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
