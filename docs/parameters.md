# Parameters

Every value below lives in `backend/autodj/config/default.yaml`. Nothing here is tuned yet: these
are starting hypotheses with stated reasons. When an experiment changes a default, record the
result in `docs/experiments.md` and update the status column.

Status legend: `hypothesis` (chosen by reasoning), `measured` (backed by a recorded experiment).

## Ingestion

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `ingestion.extensions` | mp3, wav, flac, m4a, aiff, aif, ogg, opus | Everything ffmpeg decodes that a library plausibly contains; matched case-insensitively | hypothesis |
| `ingestion.validation_seconds` | 30.0 | Long enough to prove a file decodes, short enough to keep scans fast | hypothesis |
| `ingestion.silence_scan_seconds` | 600.0 | Fallback window when the validation window is silent; only a file silent across this much audio is rejected. Longer than any single track, and it only runs on the rare silent-start file | hypothesis |
| `ingestion.min_duration_seconds` | 30.0 | Shorter files cannot host a 32-beat crossfade plus margins, so they are rejected at ingest | hypothesis |
| `ingestion.subprocess_timeout_seconds` | 120.0 | Bounds a hung ffmpeg/ffprobe on a pathological file instead of stalling the scan | hypothesis |

## Analysis

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `analysis.version` | 2 | Feature-format version; bumping it invalidates stored features. Version 2 adds the energy curve and stable regions; M2 (version 1) rows are reprocessed automatically | hypothesis |
| `analysis.sample_rate` | 22050 | Beat precision follows the onset-envelope frame rate. 44.1 kHz halves that frame period and roughly halves timing error, but BPM error is already < 0.3 after refinement at 22.05 kHz; see `docs/experiments.md` | measured |
| `analysis.hop_length` | 512 | 23.2 ms frames, the standard librosa beat-tracking grid | hypothesis |
| `analysis.refine_hop_length` | 256 | 11.6 ms envelope for sub-frame beat refinement | hypothesis |
| `analysis.start_bpm` | 124 | Weak house prior: seeds librosa's tempo estimator and breaks exact octave-score ties. Does not override a better-scoring grid farther from 124 | hypothesis |
| `analysis.min_bpm` | 80 | Below this, a grid is half-time of a house pulse and is rejected if that is the best-scoring octave | hypothesis |
| `analysis.max_bpm` | 180 | Above this, a grid is double-time; 4/4 house/techno rarely exceeds this | hypothesis |
| `analysis.min_beats` | 16 | Four bars; fewer IBIs make CV and median tempo unstable | hypothesis |
| `analysis.max_ibi_cv` | 0.12 | Whole-track CV gate, looser than `stable_regions.ibi_cv_max` because intros and outros are included. Also the zero-point of `tempo_regularity` | hypothesis |
| `analysis.min_onset_contrast` | 0.15 | Beats must be stronger than midpoints. In-memory white noise scores ~0.13 | hypothesis |
| `analysis.min_confidence` | 0.25 | Floor on the heuristic quality score (regularity × contrast), not a probability. Separate gates can both barely pass (resampled noise: product 0.05); click tracks sit above 0.6 | hypothesis |
| `analysis.refine_search_radius_frames` | 2 | ±2 fine frames is ±23 ms, one coarse frame, well inside a house beat | hypothesis |

## Energy

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `energy.alpha` | 0.6 | Weight loudness slightly above rhythmic activity; RMS is the more stable signal | hypothesis |
| `energy.rms_floor_db` / `rms_ceiling_db` | -60 / 0 | Perceptual dBFS window, immune to one loud frame | hypothesis |
| `energy.curve_hz` | 10 | Transitions care about seconds-scale energy, not frames | hypothesis |
| `energy.aggregation` | median | Resists intro/outro outliers. On a 24 s pulsed loop with a loud 2 s intro/outro, median shifted +0.013 vs mean +0.052 and p90 +0.112 | measured |
| `energy.normalization_*_percentile` | 5 / 95 | Dual use: per-track onset → `[0, 1]`, then library-wide scaling of the aggregated scalar. RMS and onset are each mapped to `[0, 1]` *before* the weighted sum | hypothesis |

## Stable regions

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `stable_regions.window_beats` | 32 | 8 bars in 4/4, matching the default crossfade length | hypothesis |
| `stable_regions.step_beats` | 4 | Dense candidates without quadratic scoring cost | hypothesis |
| `stable_regions.ibi_cv_max` | 0.06 | Steady house sits near 0.01-0.02. Synthetic 124 BPM: 2% jitter CV ≈ 0.017 (pass), 5% ≈ 0.045 (fails in-tolerance, not CV), 8% ≈ 0.076 (fails CV) | measured |
| `stable_regions.ibi_tolerance` | 0.05 | Interval counts as regular within 5% of the window median | hypothesis |
| `stable_regions.in_tolerance_fraction_min` | 0.90 | Rejects windows with sporadic spurious beats | hypothesis |
| `stable_regions.onset_strength_floor` | 0.35 | Rejects steady-but-sparse intros with no usable pulse | hypothesis |
| `stable_regions.max_regions_per_track` | 8 | Enough planning choice without pair-scoring blowup | hypothesis |
| `stable_regions.weight_*` | 0.5 / 0.3 / 0.2 | Tempo consistency dominates because drift is what breaks a mix | hypothesis |

## Retrieval and ranking

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `retrieval.max_energy_delta` | 0.25 | Drops obviously mismatched candidates before ranking. Relaxation drops this gate only | hypothesis |
| `retrieval.energy_filter_enabled` | true | Lets a set continue when every remaining track is an energy jump | hypothesis |
| `tempo.min/max_stretch_ratio` (retrieval) | 0.95 / 1.05 | Sole tempo gate. Replaces the dropped `max_bpm_deviation_pct` / `relaxed_bpm_deviation_pct` (7% exceeded this bound) | hypothesis |
| `ranking.weight_tempo` | 0.60 | Chosen prior: tempo > energy >> analysis confidence | hypothesis (M6 sweep and human check) |
| `ranking.weight_energy` | 0.35 | As above | hypothesis |
| `ranking.weight_quality` | 0.05 | Small tie-breaking penalty for low-confidence analysis | hypothesis |

## Transition and tempo

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `transition.crossfade_beats` | 32 | 8 bars, about 15.5 s at 124 BPM: long enough to beat-match, short enough to stay musical | hypothesis |
| `transition.margin_beats` | 8 | Guard band inside usable audio on both sides | hypothesis |
| `transition.outgoing_search_fraction` | [0.65, 0.95] | Mix out late, but not into the tail | hypothesis |
| `transition.incoming_search_fraction` | [0.0, 0.35] | Mix in early, skipping non-rhythmic intros | hypothesis |
| `transition.weight_*` | 0.40 / 0.30 / 0.20 / 0.10 | Stability first, then energy continuity, then stretch cost, then position | hypothesis |
| `transition.align_on_downbeat` | true | Snap to the next inferred 4/4 bar-phase beat (`index % 4 == 0`) on the M2 grid. Not true downbeat detection | hypothesis |
| `tempo.min/max_stretch_ratio` | 0.95 / 1.05 | +/-5% is benign with Rubber Band; beyond that house loses its feel | hypothesis |
| `tempo.stretch_backend` | pedalboard | Rubber Band quality via pip wheels. `rubberband_cli` and `phase_vocoder` are documented swap paths; only pedalboard is implemented | hypothesis |

## Render, session, evaluation

| Parameter | Default | Reason | Status |
| --- | --- | --- | --- |
| `render.sample_rate` / `channels` | 44100 / 2 | Preserve stereo at CD rate for mixing | hypothesis |
| `render.output_bit_depth` | 16 | 16-bit PCM WAV plays everywhere, no second lossy encode | hypothesis |
| `render.peak_ceiling_dbfs` | -1.0 | Headroom target; peaks above it are flagged. Peaks above unity are scaled into range so int16 does not wrap | hypothesis |
| `session.default_length` | 6 | Enough transitions to judge a sequence, small enough to render quickly | hypothesis |
| `session.selection_strategy` | greedy | Explainable baseline; lookahead is an M6 stretch only if greedy fails | hypothesis |
| `evaluation.excerpt_seconds` | 15.0 | Context either side of a transition for blind rating | hypothesis |
| `evaluation.pair_count` | 60 | Makes a paired sign test meaningful for a ~65/35 split | hypothesis |
