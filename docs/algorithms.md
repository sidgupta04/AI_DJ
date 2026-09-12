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

Not implemented yet. Planned: librosa dynamic-programming beat tracking on a 22.05 kHz mono
signal at a 512-sample hop, with beat times refined against a 256-sample onset envelope using
parabolic interpolation to recover sub-frame precision.

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
