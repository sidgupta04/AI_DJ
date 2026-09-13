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
the onset envelope — M4's stable-region gates are what will later refuse a track that has a
tempo but no mixable passage.

Parameters: `analysis.sample_rate`, `hop_length`, `refine_hop_length`, `start_bpm`, `min_bpm`,
`max_bpm`, `min_beats`, `max_ibi_cv`, `min_onset_contrast`, `min_confidence`,
`refine_search_radius_frames`. Changing any of these, or the octave / refinement / confidence
formulae, requires bumping `analysis.version` and reprocessing stored grids.

## Energy (M3)

Not implemented yet. Planned: `E(t) = alpha * R(t) + (1 - alpha) * O(t)`, where `R` is frame RMS
in dBFS mapped across a fixed window and `O` is normalized onset strength, scaled library-wide by
robust percentiles so cross-track comparison is meaningful.

## Stable rhythmic regions (M4)

Not implemented yet. Planned: sliding 32-beat windows stepped 4 beats, gated on inter-beat
interval coefficient of variation, the fraction of intervals near the window median, and mean
beat-position onset strength; survivors are scored and reduced by non-maximum suppression.

## Candidate retrieval and ranking (M7, M8)

Not implemented yet. Retrieval filters (analysis complete, unplayed, within tempo tolerance, has a
stable region); ranking applies the weighted tempo/energy/quality cost model.

## Transition planning (M9)

Not implemented yet. Planned: enumerate outgoing and incoming stable regions in their respective
search windows, score every pair on stability, local energy difference, required stretch, and
position preference, and choose the cheapest valid pair.

## Tempo and phase alignment (M6)

Not implemented yet. Planned: constrain candidates first, then apply a modest pitch-preserving
stretch via Rubber Band, then shift the incoming track so its chosen beat coincides with the
outgoing beat. Tempo matching prevents drift; phase alignment starts the beats together.

## Crossfade (M5)

Not implemented yet. Planned: equal-power `cos`/`sin` gain pair over the transition, with peak
measurement and clipping protection.
