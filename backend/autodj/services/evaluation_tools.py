"""Evaluation reports, blind excerpt packages and owner-supplied listener ratings."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from autodj.audio.decode import decode_to_pcm
from autodj.config.settings import Settings
from autodj.dj.baselines import Strategy
from autodj.dj.types import TrackCandidate
from autodj.metrics.summary import distribution, sign_test, summarize
from autodj.render.write import write_pcm16_wav
from autodj.services.evaluation import EvaluationService
from autodj.services.ingestion import compute_content_hash


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def comparison_run(
    service: EvaluationService,
    candidates: list[TrackCandidate],
    output: Path,
    *,
    offline_analysis: dict[str, Any] | None = None,
    strategies: tuple[Strategy, ...] = tuple(Strategy),
) -> dict[str, Any]:
    """Each ladder trial shares a seed/current track; blind trials fix both tracks separately."""
    output.mkdir(parents=True, exist_ok=False)
    cfg = service.settings
    ordered = sorted(candidates, key=lambda item: item.track_id)
    snapshot = cfg.snapshot()
    # Operational credentials are irrelevant to algorithm reproducibility and never exported.
    snapshot.pop("database_url", None)
    manifest = {
        "report_version": 1,
        "implementation_sha256": implementation_hash(),
        "config_snapshot": snapshot,
        "seed": cfg.evaluation.seed,
        "versions": {name: version(name) for name in ("autodj", "numpy", "pedalboard", "librosa")},
        "tracks": [
            {
                **asdict(track),
                "content_hash": compute_content_hash(cfg.audio_library_dir / track.audio_path)
                if (cfg.audio_library_dir / track.audio_path).is_file()
                else None,
            }
            for track in ordered
        ],
    }
    attempts = []
    for index, current in enumerate(ordered):
        for strategy in strategies:
            attempts.append(
                service.evaluate(
                    current,
                    ordered,
                    strategy=strategy,
                    seed=cfg.evaluation.seed + index,
                    output=output / "ladder" / f"{index}_{strategy}.wav",
                )
            )
    pairs = [
        (a, b)
        for a in ordered
        for b in ordered
        if a.track_id != b.track_id
        and cfg.tempo.min_stretch_ratio
        <= a.native_bpm / b.native_bpm
        <= cfg.tempo.max_stretch_ratio
    ]
    random.Random(cfg.evaluation.seed).shuffle(pairs)
    paired_attempts = []
    for index, (a, b) in enumerate(pairs[: cfg.evaluation.pair_count]):
        pair = {}
        for strategy in (Strategy.NEAREST_BPM, Strategy.FULL):
            pair[str(strategy)] = service.evaluate(
                a,
                ordered,
                strategy=strategy,
                seed=cfg.evaluation.seed + index,
                paired_track=b,
                output=output / "paired" / f"{index}_{strategy}.wav",
            )
        paired_attempts.append(pair)
    blind = export_blind_pairs(paired_attempts, output / "blind", cfg)
    report = {
        **manifest,
        "offline_analysis": offline_analysis,
        "ladder_attempts": attempts,
        "ladder_summary": summarize(attempts),
        "paired_attempts": paired_attempts,
        "paired_summary": summarize([row for pair in paired_attempts for row in pair.values()]),
        "blind_export": blind,
    }
    write_json(output / "report.json", report)
    return report


def implementation_hash() -> str:
    """Fingerprint implementation/config without exporting source, credentials or private audio."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        *root.glob("backend/autodj/**/*.py"),
        *root.glob("scripts/*.py"),
        root / "pyproject.toml",
        root / "uv.lock",
        root / "backend/autodj/config/default.yaml",
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def export_blind_pairs(
    pairs: list[dict[str, dict[str, Any]]],
    destination: Path,
    settings: Settings,
) -> dict[str, Any]:
    """Participant folder contains generic WAV names and empty ratings only; key stays outside."""
    participant = destination / "participants"
    participant.mkdir(parents=True, exist_ok=False)
    rng = random.Random(settings.evaluation.seed)
    key: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        b, d = pair["B"], pair["D"]
        if any(row["status"] != "RENDERED" for row in (b, d)):
            failures.append({"index": index, "reason": "PAIR_RENDER_FAILED"})
            continue
        if (b["track_a_id"], b["track_b_id"]) != (d["track_a_id"], d["track_b_id"]):
            raise ValueError("blind B/D must use identical ordered track pairs")
        if b["sample_rate"] != d["sample_rate"] or b["fade_frames"] != d["fade_frames"]:
            raise ValueError("blind pair must have identical rate and overlap duration")
        context = round(settings.evaluation.excerpt_seconds * b["sample_rate"])
        pre = min(context, b["fade_start_sample"], d["fade_start_sample"])
        post = min(
            context,
            *(row["frames"] - row["fade_start_sample"] - row["fade_frames"] for row in (b, d)),
        )
        labels = ["B", "D"]
        rng.shuffle(labels)
        pair_id = f"pair_{index + 1:03d}"
        key[pair_id] = {
            "track_a_id": b["track_a_id"],
            "track_b_id": b["track_b_id"],
            "X": labels[0],
            "Y": labels[1],
            "pre_seconds": pre / b["sample_rate"],
            "post_seconds": post / b["sample_rate"],
        }
        for label, model in zip(("X", "Y"), labels, strict=True):
            row = pair[model]
            audio = decode_to_pcm(
                Path(row["wav_path"]),
                sample_rate=row["sample_rate"],
                channels=settings.render.channels,
                timeout=settings.ingestion.subprocess_timeout_seconds,
            )
            start = row["fade_start_sample"] - pre
            excerpt = audio[start : row["fade_start_sample"] + row["fade_frames"] + post]
            write_pcm16_wav(
                participant / f"{pair_id}_{label}.wav", excerpt, sample_rate=row["sample_rate"]
            )
    columns = [
        "listener_id",
        "pair_id",
        "smoothness_X",
        "smoothness_Y",
        "rhythm_X",
        "rhythm_Y",
        "energy_X",
        "energy_Y",
        "preference",
    ]
    with (participant / "ratings.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for listener in range(settings.evaluation.minimum_listeners):
            for pair_id in key:
                writer.writerow({"listener_id": f"listener_{listener + 1}", "pair_id": pair_id})
    (participant / "README.txt").write_text(
        "Listen to X and Y for each pair. Rate smoothness, rhythmic coherence and energy "
        "continuity from 1 (poor) to 5 (excellent). Preference: X, Y or tie. "
        "Use a distinct listener_id per person. Do not share the administrator codebook.\n"
    )
    write_json(destination / "codebook.json", key)
    return {
        "requested": settings.evaluation.pair_count,
        "attempted": len(pairs),
        "exported": len(key),
        "failures": failures,
        "shortfall": max(0, settings.evaluation.pair_count - len(key)),
    }


def analyze_ratings(ratings: Path, codebook: Path, *, minimum_listeners: int) -> dict[str, Any]:
    """Pair is the independent unit: aggregate listeners before applying the sign test."""
    key = json.loads(codebook.read_text())
    votes: dict[str, list[int]] = defaultdict(list)
    listeners: dict[str, set[str]] = defaultdict(set)
    scores: dict[str, list[float]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    with ratings.open(newline="") as handle:
        for row in csv.DictReader(handle):
            pair_id, listener = row["pair_id"], row["listener_id"].strip()
            if pair_id not in key or not listener or (pair_id, listener) in seen:
                raise ValueError("unknown pair, missing listener, or duplicate listener/pair")
            seen.add((pair_id, listener))
            preference = row["preference"]
            if preference not in ("X", "Y", "tie"):
                raise ValueError("preference must be X, Y or tie; incomplete rows are not votes")
            values: dict[str, int] = {}
            for dimension in ("smoothness", "rhythm", "energy"):
                for label in ("X", "Y"):
                    value = int(row[f"{dimension}_{label}"])
                    if not 1 <= value <= 5:
                        raise ValueError("ratings must be integers 1 through 5")
                    values[f"{dimension}_{key[pair_id][label]}"] = value
                scores[f"{dimension}_D_minus_B"].append(
                    float(values[f"{dimension}_D"] - values[f"{dimension}_B"])
                )
            votes[pair_id].append(
                0 if preference == "tie" else (1 if key[pair_id][preference] == "D" else -1)
            )
            listeners[pair_id].add(listener)
    eligible = [pair_id for pair_id in key if len(listeners[pair_id]) >= minimum_listeners]
    outcomes = Counter(int(np.sign(sum(votes[pair_id]))) for pair_id in eligible)
    return {
        "rated_pairs": len(votes),
        "eligible_pairs": len(eligible),
        "insufficient_listener_pairs": len(key) - len(eligible),
        "D_wins": outcomes[1],
        "B_wins": outcomes[-1],
        "ties": outcomes[0],
        "two_sided_sign_test_p": sign_test(outcomes[1], outcomes[-1]),
        "rating_deltas_descriptive_only": {
            name: distribution(values) for name, values in scores.items()
        },
        "unit": "ordered track pair; majority preference across listeners; tied pairs excluded",
    }
