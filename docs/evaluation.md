# Evaluation

A working demo is not evidence. Each added piece of the algorithm must be shown to help, or shown
not to.

## Model ladder

Every model is a selectable strategy so results are reproducible from a config snapshot and a seed
track.

- Baseline A — random next track.
- Baseline B — nearest BPM, fixed crossfade near the track edge.
- Model C — BPM + energy compatibility ranking.
- Model D — C plus stable-region transition selection and beat alignment.
- Model E — D plus bounded lookahead sequencing (M13).

## Objective metrics

Recorded per transition (see the `transitions` table) and reported as distributions, not averages:

- native BPM delta and stretch percentage;
- measured beat-alignment error in ms, from onset-envelope cross-correlation of the two stems
  inside the overlap, not from the planned arithmetic;
- local energy discontinuity across the transition;
- chosen region stability scores;
- transition success and failure rates by failure type;
- planning and render latency (p50/p95/p99), plus offline analysis duration and failure rate.

## Human evaluation (M12)

60 transition pairs, baseline B versus model D on identical track pairs, presented blind and
order-randomized to at least three listeners. Ratings: smoothness, rhythmic coherence, and energy
continuity on 1-5 scales, plus an overall A/B preference. Analyzed with a paired sign test and
reported alongside the config snapshot that produced the audio.

## Results

None yet. Results land here as milestones complete, each with the config snapshot and the command
used to produce them.
