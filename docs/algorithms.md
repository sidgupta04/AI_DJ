# Algorithms

Each section is written by the milestone that implements it, and must state what the algorithm
does, why it was chosen over the alternatives, and which configuration parameters govern it.

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
