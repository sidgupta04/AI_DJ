# Algorithms

Each section is written by the milestone that implements it, and must state what the algorithm
does, why it was chosen over the alternatives, and which configuration parameters govern it.

## Track naming (M1)

Produces a display title and artist for a source file, and records which source it came from
(`tags`, `filename`, or `mixed`).

Embedded metadata is preferred because it is the only structured signal available. Tag keys vary by
encoder, so several aliases are accepted (`title`/`tit2`, `artist`/`artst`/`tpe1`/`album_artist`),
and known placeholders (`unknown`, `untitled`, `track`, `n/a`, ...) are rejected as if absent.

When a tag is missing the filename stem is sanitized, deliberately conservatively:

1. Strip bracketed noise only when its contents match a known-noise vocabulary — official
   video/audio/visualizer, lyrics, `hd`/`hq`/`4k`/`1080p`, free download, explicit, clean. This
   keeps musically meaningful parentheses such as `(Extended Mix)`, `(feat. ...)`, `(Radio Edit)`,
   and `(Remastered 2011)`.
2. Strip a leading track number (`03 - `, `07. `).
3. Strip a trailing `- Topic` (a YouTube auto-channel artifact).
4. Convert underscores to spaces and collapse whitespace.
5. Trim edge junk, but never trailing periods: `HUMBLE.` and `Fred again..` are real names.
6. Split on the *first* spaced dash (hyphen, en dash, or em dash) and only claim an artist when
   both sides have content. `Bad Bunny, Drake - MIA` therefore yields artist `Bad Bunny, Drake`,
   while `Untitled Loop` yields no artist rather than a guess.
7. Truncate each field to 500 characters so a pathological filename cannot poison the database.

The alternative — assuming `Artist - Title.mp3` — was rejected: it invents artists for files that
have none and mangles titles containing dashes.

## Decode and validation (M1)

ffprobe reports duration, sample rate, channels, codec, bit rate, and tags as JSON; ffmpeg decodes
to raw mono float32 (`-f f32le`) at a requested sample rate, optionally windowed with `-t`. Both
run as argument lists (never through a shell) with absolute paths, so spaces, quotes, and leading
dashes in filenames are inert.

Validation decodes only `ingestion.validation_seconds` of audio: enough to prove the file is
readable without paying for a full decode during a scan. Every rejection maps to a named
`SourceFailure` so the cause is queryable later rather than a lost log line.

Silence is handled in two stages, because a quiet opening says nothing about a track. If the
validation window has no audible peak, the check re-decodes up to `ingestion.silence_scan_seconds`
and assigns `SILENT_AUDIO` only when that longer stretch is also silent. Sampling a couple of fixed
offsets instead would be cheaper but can still reject a valid file whose audible content happens to
fall between the samples; widening the window has no such blind spot, and it only runs on the rare
file that trips the first check.

## Beat and tempo analysis (M2)

Produces a native BPM, a beat grid in seconds, and a heuristic beat-grid quality score
from mono PCM.

The signal is analysed at `analysis.sample_rate` (22.05 kHz) with hop `analysis.hop_length`
(512 samples, 23.2 ms). librosa's onset envelope and dynamic-programming `beat_track` propose a
grid. `analysis.start_bpm` (124) is a **weak prior**, used in exactly two places and nowhere
as a target the answer is pulled toward:

- It is librosa's tempo-estimator prior (a log-normal centred on 124). That biases the *first*
  proposed grid, the same way librosa's own `start_bpm` always has. A 100 BPM click track still
  comes out near 100, not 124.
- After we score octaves, it breaks **exact score ties only**. 87 vs 174 with equal onset
  evidence prefers 87 (`|87 − 124| < |174 − 124|`). If 174's score is even slightly higher,
  174 wins. Musical evidence dominates; the prior never outweighs a better lock.

That proposal is quantized to the hop, so two further steps recover a tempo a DJ can use:

1. **Tempo from the grid, not from librosa's global estimate.** `native_bpm = 60 / median(Δt)`
   of the chosen beat times. The median IBI is the spacing of the beats we will actually align;
   librosa's scalar tempo is discarded.
2. **Octave disambiguation.** Half-time and double-time are scored, not guessed. The raw grid
   is evaluated at 0.5x (even beats and odd beats separately), 1x, and 2x (original beats plus
   inserted midpoints). Each candidate gets
   `score = mean(onset at beats) * max(0, onset_contrast)`, where
   `onset_contrast = (μ_on − μ_off) / (μ_on + μ_off)` and `μ_off` is the mean envelope at the
   midpoints between beats. Contrast kills half-time (the dropped beats become strong off-beats).
   Mean-onbeat kills double-time (half the inserted beats land on silence). The highest-scoring
   candidate wins; `start_bpm` breaks only exact ties, as above. If that winner lies outside
   `[min_bpm, max_bpm]`, analysis fails with `TEMPO_OUT_OF_RANGE` rather than silently folding
   a slow pulse into the house band.
3. **Sub-frame refinement.** Each surviving beat is moved to the peak of a second onset
   envelope computed at `refine_hop_length` (256 samples, 11.6 ms), searching
   `refine_search_radius_frames` on either side. A 3-point parabola through that peak,
   `δ = ½ (y[i−1] − y[i+1]) / (y[i−1] − 2y[i] + y[i+1])`, places the time between frames.
   BPM, IBI CV and contrast are then recomputed on the refined grid.

The alternative — trusting librosa's tempo and frame-quantized beats — was rejected because a
perfect 120 BPM click track lands on a 22-hop IBI (117.5 BPM) until refinement, and because a
62-vs-124 decision needs the onset envelope, not a house-tempo prior.

### analysis_confidence

`analysis_confidence` is a **heuristic beat-grid quality score in [0, 1]**. It is **not** a
calibrated probability that the BPM is correct. `0.72` means "this grid scored 0.72 on the
deterministic quality measure below", not "there is a 72% chance this tempo is right."

The column name is kept because later ranking already talks about a quality term
(`ranking.weight_quality`). After the refined grid is accepted:

```text
tempo_regularity     = max(0, 1 − ibi_cv / max_ibi_cv)
onset_score          = max(0, onset_contrast)
analysis_confidence  = tempo_regularity × onset_score
```

`ibi_cv` is the coefficient of variation of the inter-beat intervals. Regularity is 1 on a
metronomic grid and 0 at the hard failure threshold. `onset_contrast` is 1 when the envelope
sits on the beats and not between them, and 0 when beats and midpoints are interchangeable.
The product is high only when both are true. A perfectly regular grid on noise has low
contrast; a strongly pulsed but wandering performance has low regularity.

Hard failures (no BPM is stored):

| Reason | When |
| --- | --- |
| `TOO_FEW_BEATS` | librosa returned fewer than 2 beats, or the refined grid has fewer than `min_beats` |
| `TEMPO_OUT_OF_RANGE` | the best-scoring octave is outside `[min_bpm, max_bpm]` |
| `IRREGULAR_BEAT_GRID` | refined `ibi_cv` exceeds `max_ibi_cv` |
| `WEAK_ONSET_ALIGNMENT` | refined onset contrast is below `min_onset_contrast` |
| `LOW_CONFIDENCE` | quality score is below `min_confidence` even though the two factors cleared their own gates |
| `EMPTY_ONSET_ENVELOPE` | the onset envelope is empty or non-finite |
| `MISSING_FILE` | the source path is gone (service-level) |

A failure never stops the batch. The track stays in the table as `FAILED` with the reason in
`failure_reason`, and `native_bpm` / `analysis_confidence` / `analysis_version` are cleared.
Known limitation: librosa's DP tracker will invent a fairly regular grid on irregular material,
so IBI CV alone does not catch every unusable file. Contrast rejects in-memory white noise
(~0.13, below `min_onset_contrast` 0.15). Resampled noise can clear that floor with a product
around 0.05; `min_confidence` is what rejects it. A pure sine can still look like a pulse in
the onset envelope — M3's stable-region gates refuse a track that has a tempo but no mixable
passage (`NO_STABLE_REGION`).

Parameters: `analysis.sample_rate`, `hop_length`, `refine_hop_length`, `start_bpm`, `min_bpm`,
`max_bpm`, `min_beats`, `max_ibi_cv`, `min_onset_contrast`, `min_confidence`,
`refine_search_radius_frames`. Changing any of these, or the octave / refinement / confidence
formulae, requires bumping `analysis.version` and reprocessing stored grids.

## Energy (M3)

Produces a 10 Hz energy curve in `[0, 1]` and an aggregated scalar used later for retrieval.

RMS and onset are **normalized onto `[0, 1]` first**, then mixed. Adding a raw dBFS number
to a raw onset number would let units, not musical weight, decide the mix.

1. Frame RMS at `analysis.hop_length` is converted to dBFS and mapped linearly through
   `[energy.rms_floor_db, energy.rms_ceiling_db]`, then clamped to `[0, 1]`. The window is
   absolute, so a louder track scores higher than a quieter one before any library scaling.
2. Onset strength at the same hop is mapped through that track's
   `energy.normalization_low_percentile` / `high_percentile` (5th/95th). Onset magnitude is
   relative; the percentiles put it on the same scale as the RMS unit signal.
3. `E(t) = alpha * R(t) + (1 - alpha) * O(t)` with `energy.alpha = 0.6`.
4. The hop-rate curve is interpolated onto a `energy.curve_hz` (10 Hz) grid and stored.
5. A per-track scalar is the configured aggregation of that curve. The M3 experiment on a
   24 s pulsed loop with a loud 2 s intro and outro found median shift +0.013 versus mean
   +0.052 and p90 +0.112, so `energy.aggregation` stays `median`.
6. After a batch, every COMPLETE track at the current `analysis.version` has its scalar
   mapped through the library 5th/95th of those scalars and written to `tracks.energy`.
   Tracks analysed in earlier invocations are rewritten too. The stored curve is left
   per-track so local gaps inside a transition window stay meaningful. A one-track library,
   or a library whose 5th and 95th coincide, keeps the unscaled scalar.

Parameters: `energy.alpha`, `rms_floor_db`, `rms_ceiling_db`, `curve_hz`, `aggregation`,
`normalization_low_percentile`, `normalization_high_percentile`. Changing any of these, or
the order of normalization versus mixing, requires bumping `analysis.version` and
reprocessing.

## Stable rhythmic regions (M3)

Produces up to `stable_regions.max_regions_per_track` (8) non-overlapping mixable windows
on the refined beat grid.

Candidate windows are `window_beats` (32) long, stepped `step_beats` (4). A window survives
only if all three gates pass:

- IBI coefficient of variation ≤ `ibi_cv_max` (0.06);
- fraction of intervals within `ibi_tolerance` (5%) of the window median ≥
  `in_tolerance_fraction_min` (0.90);
- mean unit-mapped onset at the window's beats ≥ `onset_strength_floor` (0.35).

Survivors are scored
`w_tempo * (1 − ibi_cv / ibi_cv_max) + w_onset * mean_onset + w_tol * in_tolerance`,
then reduced by non-maximum suppression: highest score first, drop any overlap, stop at 8.
Remaining regions are stored in beat-index order.

A grid with fewer than 32 beats, or with no surviving window, fails analysis with
`NO_STABLE_REGION`. Tempo without a mixable passage is not a completed track; BPM is not
kept. The M3 calibration on synthetic 124 BPM grids: a perfect grid and 2% time jitter
(CV ≈ 0.017, typical tight house) pass; 5% jitter is rejected by the in-tolerance gate
before CV; 8% jitter exceeds `ibi_cv_max`; a steady grid with onset 0.05 fails the onset
floor. Defaults were left unchanged.

Parameters: `stable_regions.window_beats`, `step_beats`, `ibi_cv_max`, `ibi_tolerance`,
`in_tolerance_fraction_min`, `onset_strength_floor`, `max_regions_per_track`, `weight_*`.
Changing the gates or the window length requires bumping `analysis.version`.

## Candidate retrieval and ranking (M4)

From a playing track, decide which library rows are plausible and which of those is best.
No audio is written.

**Retrieval** (`autodj.dj.retrieve`) is a hard filter, then one optional relaxation:

1. Drop the current track, already-played tracks (unless `retrieval.allow_repeats`),
   tracks with no stable region (when `retrieval.require_stable_region`), and any row
   whose `session_bpm / native_bpm` is outside
   `[tempo.min_stretch_ratio, tempo.max_stretch_ratio]`.
2. If `retrieval.energy_filter_enabled`, keep only rows whose library-normalised
   `|energy − current.energy| ≤ retrieval.max_energy_delta`.
3. If that energy gate leaves nobody, **drop only the energy gate**. The stretch bound
   is never widened. The old `relaxed_bpm_deviation_pct: 7.0` hypothesis was dropped
   because 7% exceeds the ±5% renderer limit.

Incomplete, failed, and stale-`analysis.version` rows never reach this function: the
service loads only COMPLETE rows at the current feature version.

**Ranking** (`autodj.dj.rank`) scores the survivors. Lower is better:

```text
stretch           = session_bpm / native_bpm
max_dev           = max(max_stretch_ratio − 1, 1 − min_stretch_ratio)
tempo_cost        = min(1, |stretch − 1| / max_dev)
energy_cost       = |candidate.energy − current.energy|          # library-normalised
quality_cost      = 1 − analysis_confidence
total_cost        = w_tempo·tempo_cost + w_energy·energy_cost + w_quality·quality_cost
```

Weights (`0.60 / 0.35 / 0.05`) sum to 1. Ties break on `track_id` ascending. After
relaxation, energy_cost still orders the list — the gate is gone, the ranking term is not.

## Transition planning (M4)

Given tracks A (playing) and B (next), pick the cheapest exit/enter window pair.

Outgoing regions whose midpoint fraction of A's duration falls in
`transition.outgoing_search_fraction` `[0.65, 0.95]` are paired with incoming regions
whose midpoint fraction of B falls in `[0.0, 0.35]`. Stretch outside the same
`tempo.min/max_stretch_ratio` bound yields no plan.

```text
stretch_ratio     = session_bpm / B.native_bpm
stretch_cost      = min(1, |stretch_ratio − 1| / max_dev)
stability_cost    = clip(1 − (score_out + score_in) / 2, 0, 1)
energy_cost       = |out.mean_energy − in.mean_energy|           # local curve means
out_pos, in_pos   = midpoint / duration
out_dev           = |out_pos − center_out| / half_out            # 0 at centre, 1 at edge
in_dev            = |in_pos − center_in| / half_in
position_cost     = (out_dev + in_dev) / 2
pair_cost         = 0.40·stability + 0.30·energy + 0.20·stretch + 0.10·position
```

`mean_energy` is the mean of M3's per-track `[0, 1]` curve in that window (RMS is
absolute dBFS; onset is per-track). That is the local gap the curve was stored for.
Library-normalised `tracks.energy` is used only in retrieval/ranking.

Ties break on `(outgoing.start_beat, incoming.start_beat)` ascending. If the top-ranked
B has no pair in-window, the service walks the ranked list until one does.

## Tempo and phase alignment (M5)

Turns an M4 `TransitionPlan` into aligned PCM. Each stem is stretched once, constantly,
pitch-preserving, by `session_bpm / native_bpm`. The seed track's native BPM is the
initial V1 session-tempo default; a later policy may pick a different constant. Continuous
ramps are out of scope.

```text
stretch_ratio     = session_bpm / native_bpm          # per stem
pedalboard factor = stretch_ratio                     # >1 is faster and shorter
t'                = t / stretch_ratio                 # linear beat-grid remap
```

The renderer refuses a ratio outside `[tempo.min_stretch_ratio, tempo.max_stretch_ratio]`
(±5%, the same hard bound M4 already applied). `rubberband_cli` and `phase_vocoder` remain
documented swap paths behind `tempo.stretch_backend`; only `pedalboard` is implemented.

The coincidence beat is the region's `start_beat`, or — when
`transition.align_on_downbeat` is true — the first inferred 4/4 bar-phase boundary
inside the region (`beat_index % 4 == 0`, treating beat 0 as bar 1). M2 does not
detect true musical downbeats; this is grid/bar phase only. The incoming stem is
delayed so those two beats share a mix sample; tempo matching then keeps them
together for the rest of the overlap.

## Crossfade (M5)

Equal-power `cos` / `sin` over `transition.crossfade_beats` *intervals* at session
tempo (32 beats = 32 inter-beat periods = 8 bars in 4/4), with `margin_beats` of
outgoing audio before the fade and incoming audio after it. The fade is the
half-open sample range `[align, align + fade_frames)`.

```text
T                 = crossfade_beats × 60 / session_bpm   # interval span, not N timestamps
fade_frames       = round(T × sample_rate)
u                 = 0 … 1 across fade_frames
g_out(u)          = cos(π/2 × u)
g_in(u)           = sin(π/2 × u)          # g_out² + g_in² = 1
peak_dbfs         = 20 log10(max |mix|)
peak_exceeded     = peak_dbfs > render.peak_ceiling_dbfs
clipped           = peak > 1 before protection
```

If the unprotected peak exceeds unity the mix is scaled into `[-1, 1]` so int16 does not
wrap. Peaks between the ceiling (−1 dBFS) and unity are flagged, not scaled. The WAV is
16-bit PCM stereo at `render.sample_rate`, written under `AUTODJ_RENDER_CACHE_DIR/transitions/`
via a sibling `.tmp` then rename so a crash cannot leave a truncated published file.
A `transitions` row is marked `RENDERED` only after that rename succeeds; failures store
`FAILED` with no `wav_path` and discard any partial attempt.
