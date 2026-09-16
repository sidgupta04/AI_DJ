#!/usr/bin/env python3
"""Reproducible M6 synthetic model ladder with known grids; no private library or database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from autodj.config.settings import load_settings
from autodj.dj.types import RegionInfo, TrackCandidate
from autodj.render.write import write_pcm16_wav
from autodj.services.evaluation import EvaluationService
from autodj.services.evaluation_tools import comparison_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory under render_cache"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = args.output / "sources"
    sources.mkdir()
    settings = load_settings(env_file=None)
    settings = settings.model_copy(update={"audio_library_dir": sources.resolve()})
    # Dataset constants, not production tunables. Planted grids isolate M4/M5 from M2 errors.
    sample_rate, seconds = settings.render.sample_rate, 80.0
    fixtures = [(120.0, 0.0, 0.2), (121.0, 0.12, 0.2), (124.0, 0.23, 0.55), (138.0, 0.31, 0.2)]
    candidates = []
    for index, (bpm, phase, amplitude) in enumerate(fixtures, 1):
        beats = np.arange(phase, seconds, 60 / bpm)
        audio = np.zeros((round(seconds * sample_rate), 2), dtype=np.float32)
        pulse = (
            amplitude * np.exp(-np.arange(round(0.02 * sample_rate)) / (0.004 * sample_rate))
        ).astype(np.float32)
        for beat in beats:
            start = round(beat * sample_rate)
            end = min(len(audio), start + len(pulse))
            audio[start:end] += pulse[: end - start, None]
        path = f"track_{index}.wav"
        write_pcm16_wav(sources / path, audio, sample_rate=sample_rate)
        starts = [8, int(len(beats) * 0.7) // 4 * 4]
        regions = [
            RegionInfo(
                start,
                start + 32,
                float(beats[start]),
                float(beats[start + 31]),
                1.0,
                0.0,
                amplitude,
            )
            for start in starts
        ]
        candidates.append(
            TrackCandidate(
                index,
                path,
                bpm,
                amplitude,
                1.0,
                settings.analysis.version,
                seconds,
                regions,
                beats.tolist(),
                len(beats),
            )
        )
    report = comparison_run(EvaluationService(settings), candidates, args.output / "comparison")
    print(
        json.dumps(
            {
                "ladder": report["ladder_summary"],
                "paired": report["paired_summary"],
                "blind": report["blind_export"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
