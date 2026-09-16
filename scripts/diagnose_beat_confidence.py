#!/usr/bin/env python3
"""Read-only M2 diagnostic for selected BPM, confidence components, and pre-gate regions.

Usage:
    uv run python scripts/diagnose_beat_confidence.py --all --output analysis_cache/confidence.json
    uv run python scripts/diagnose_beat_confidence.py --path "Levels - Avicii (Lyrics).mp3"
    uv run python scripts/diagnose_beat_confidence.py --all \\
        --click-output-dir analysis_cache/beat-clicks

This deliberately reproduces the analysis stages through region detection without applying
the confidence rejection. It never writes the database or source library; optional click
overlays are separate diagnostic WAVs.
"""

from __future__ import annotations

import argparse
import json
import os
import wave
from pathlib import Path
from typing import Any, cast

import librosa
import numpy as np

from autodj.audio.beats import (
    AnalysisFailure,
    BeatTrackingError,
    _bpm_from_times,
    _choose_octave,
    _ibi_cv,
    _onset_alignment,
    refine_beat_times,
)
from autodj.audio.decode import SourceError, decode_to_mono
from autodj.audio.energy import analyze_energy
from autodj.audio.regions import RegionDetectionError, detect_stable_regions
from autodj.config.settings import Settings, load_settings
from autodj.persistence.database import build_engine, build_session_factory, session_scope
from autodj.persistence.models import Track
from autodj.persistence.repositories import TrackRepository

_CLICK_DURATION_SECONDS = 0.03
_CLICK_FREQUENCY_HZ = 1760.0
_CLICK_AMPLITUDE = 0.65
_OUTPUT_PEAK_CEILING = 0.98


def diagnose(samples: np.ndarray, settings: Settings) -> dict[str, Any]:
    """Run the same M2/M3 extraction through regions, retaining pre-confidence evidence."""
    analysis = settings.analysis
    if samples.ndim != 1 or samples.size == 0:
        return {"failure": {"reason": str(AnalysisFailure.EMPTY_ONSET_ENVELOPE)}}

    onset = librosa.onset.onset_strength(
        y=samples, sr=analysis.sample_rate, hop_length=analysis.hop_length
    )
    if onset.size == 0 or not bool(np.isfinite(onset).all()):
        return {"failure": {"reason": str(AnalysisFailure.EMPTY_ONSET_ENVELOPE)}}
    _, raw_beats = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=analysis.sample_rate,
        hop_length=analysis.hop_length,
        start_bpm=analysis.start_bpm,
        units="time",
    )
    raw = np.asarray(raw_beats, dtype=np.float64)
    if raw.size < 2:
        return {
            "failure": {"reason": str(AnalysisFailure.TOO_FEW_BEATS)},
            "raw_beat_count": int(raw.size),
        }
    try:
        candidate = _choose_octave(
            raw,
            onset,
            sample_rate=analysis.sample_rate,
            hop_length=analysis.hop_length,
            start_bpm=analysis.start_bpm,
            min_bpm=analysis.min_bpm,
            max_bpm=analysis.max_bpm,
        )
    except BeatTrackingError as error:
        return {"failure": error.as_dict(), "raw_beat_count": int(raw.size)}

    fine_onset = librosa.onset.onset_strength(
        y=samples, sr=analysis.sample_rate, hop_length=analysis.refine_hop_length
    )
    beats = refine_beat_times(
        candidate.times,
        fine_onset,
        sample_rate=analysis.sample_rate,
        hop_length=analysis.refine_hop_length,
        search_radius=analysis.refine_search_radius_frames,
    )
    if beats.size < analysis.min_beats:
        return {
            "failure": {"reason": str(AnalysisFailure.TOO_FEW_BEATS)},
            "raw_beat_count": int(raw.size),
            "selected_beat_count": int(beats.size),
        }

    native_bpm = _bpm_from_times(beats)
    ibi_cv = _ibi_cv(beats)
    contrast, _mean_onbeat = _onset_alignment(
        beats,
        fine_onset,
        sample_rate=analysis.sample_rate,
        hop_length=analysis.refine_hop_length,
    )
    regularity = max(0.0, 1.0 - ibi_cv / analysis.max_ibi_cv)
    confidence = regularity * max(0.0, contrast)
    result: dict[str, Any] = {
        "selected_native_bpm": native_bpm,
        "selected_octave_factor": candidate.octave_factor,
        "tempo_regularity": regularity,
        "onset_contrast": contrast,
        "final_confidence": confidence,
        "confidence_threshold": analysis.min_confidence,
        "ibi_cv": ibi_cv,
        "beat_count": int(beats.size),
        "beat_timestamps_seconds": [round(float(value), 6) for value in beats],
        "gates": {
            "tempo_in_range": analysis.min_bpm <= native_bpm <= analysis.max_bpm,
            "regularity": ibi_cv <= analysis.max_ibi_cv,
            "onset": contrast >= analysis.min_onset_contrast,
            "confidence": confidence >= analysis.min_confidence,
        },
    }
    result["stable_regions"] = _diagnose_regions(samples, beats, settings)
    # The serialized report intentionally rounds timestamps for readability. Keep the
    # original refined values private so optional click exports use the exact grid.
    result["_refined_beats"] = beats
    return result


def overlay_beat_clicks(
    samples: np.ndarray, beat_times: np.ndarray, *, sample_rate: int
) -> np.ndarray:
    """Return mono audio with short decaying clicks at exact beat sample positions.

    A single peak-normalization step keeps both the original audio and clicks audible
    while ensuring the PCM writer cannot clip.
    """
    original = np.asarray(samples, dtype=np.float32)
    if original.ndim != 1:
        raise ValueError(f"expected mono samples, got shape {original.shape}")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    click_length = max(1, round(_CLICK_DURATION_SECONDS * sample_rate))
    indices = np.arange(click_length, dtype=np.float32)
    envelope = np.exp(-6.0 * indices / max(1, click_length - 1))
    click = (
        _CLICK_AMPLITUDE
        * np.cos(2.0 * np.pi * _CLICK_FREQUENCY_HZ * indices / sample_rate)
        * envelope
    ).astype(np.float32)
    mixed = np.array(original, copy=True)
    for timestamp in np.asarray(beat_times, dtype=np.float64):
        start = round(float(timestamp) * sample_rate)
        if start < 0 or start >= mixed.size:
            continue
        end = min(start + click_length, mixed.size)
        mixed[start:end] += click[: end - start]

    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > _OUTPUT_PEAK_CEILING:
        mixed *= _OUTPUT_PEAK_CEILING / peak
    return mixed


def _write_click_overlay_wav(path: Path, samples: np.ndarray, *, sample_rate: int) -> None:
    """Write a mono 16-bit PCM diagnostic WAV without overwriting an existing file."""
    if path.exists():
        raise FileExistsError(f"click overlay output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.round(samples * 32767.0), -32768, 32767).astype("<i2")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with wave.open(str(tmp_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(np.ascontiguousarray(pcm).tobytes())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _click_output_path(directory: Path, track: Track) -> Path:
    """Derive a collision-resistant diagnostic filename from the immutable track ID."""
    return directory / f"{track.id}-{Path(track.audio_path).stem}.beats.wav"


def _diagnose_regions(samples: np.ndarray, beats: np.ndarray, settings: Settings) -> dict[str, Any]:
    """M3 region result using the selected grid, independent of confidence acceptance."""
    energy_cfg = settings.energy
    region_cfg = settings.stable_regions
    energy = analyze_energy(
        samples,
        sample_rate=settings.analysis.sample_rate,
        hop_length=settings.analysis.hop_length,
        alpha=energy_cfg.alpha,
        rms_floor_db=energy_cfg.rms_floor_db,
        rms_ceiling_db=energy_cfg.rms_ceiling_db,
        curve_hz=energy_cfg.curve_hz,
        aggregation=energy_cfg.aggregation,
        onset_low_percentile=energy_cfg.normalization_low_percentile,
        onset_high_percentile=energy_cfg.normalization_high_percentile,
    )
    try:
        regions = detect_stable_regions(
            beats,
            onset_unit=energy.onset_unit,
            sample_rate=energy.sample_rate,
            hop_length=energy.hop_length,
            energy_curve=energy.curve,
            energy_curve_hz=energy.curve_hz,
            window_beats=region_cfg.window_beats,
            step_beats=region_cfg.step_beats,
            ibi_cv_max=region_cfg.ibi_cv_max,
            ibi_tolerance=region_cfg.ibi_tolerance,
            in_tolerance_fraction_min=region_cfg.in_tolerance_fraction_min,
            onset_strength_floor=region_cfg.onset_strength_floor,
            max_regions_per_track=region_cfg.max_regions_per_track,
            weight_tempo_consistency=region_cfg.weight_tempo_consistency,
            weight_onset_strength=region_cfg.weight_onset_strength,
            weight_in_tolerance=region_cfg.weight_in_tolerance,
        )
    except RegionDetectionError as error:
        return {"regions": [], "failure": error.as_dict(), "energy_scalar": energy.scalar}
    return {
        "regions": [region.as_dict() for region in regions],
        "failure": None,
        "energy_scalar": energy.scalar,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="diagnose every ingested track")
    group.add_argument("--path", action="append", help="library-relative path; repeatable")
    parser.add_argument(
        "--library-dir",
        type=Path,
        help="override AUTODJ_AUDIO_LIBRARY_DIR without changing configuration or database state",
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path; must not exist")
    parser.add_argument(
        "--click-output-dir",
        type=Path,
        help="optional directory for read-only WAVs with predicted-beat clicks",
    )
    args = parser.parse_args()
    settings = load_settings()
    if args.library_dir is not None:
        settings = settings.model_copy(update={"audio_library_dir": args.library_dir})
    engine = build_engine(settings)
    try:
        factory = build_session_factory(engine)
        with session_scope(factory) as session:
            repository = TrackRepository(session)
            tracks: list[Track | None]
            if args.all:
                tracks = [cast(Track | None, track) for track in repository.list_tracks()]
            else:
                tracks = [repository.get_by_path(path) for path in args.path]
        rows: list[dict[str, Any]] = []
        for track in tracks:
            if track is None:
                rows.append({"failure": {"reason": "MISSING_TRACK"}})
                continue
            row: dict[str, Any] = {"track_id": track.id, "audio_path": track.audio_path}
            try:
                samples = decode_to_mono(
                    settings.audio_library_dir / track.audio_path,
                    sample_rate=settings.analysis.sample_rate,
                    timeout=settings.ingestion.subprocess_timeout_seconds,
                )
                diagnostic = diagnose(samples, settings)
                refined_beats = diagnostic.pop("_refined_beats", None)
                row.update(diagnostic)
                if args.click_output_dir is not None and isinstance(refined_beats, np.ndarray):
                    destination = _click_output_path(args.click_output_dir, track)
                    overlay = overlay_beat_clicks(
                        samples,
                        refined_beats,
                        sample_rate=settings.analysis.sample_rate,
                    )
                    _write_click_overlay_wav(
                        destination,
                        overlay,
                        sample_rate=settings.analysis.sample_rate,
                    )
                    row["click_overlay_wav"] = str(destination)
            except SourceError as error:
                row["failure"] = error.as_dict()
            rows.append(row)
        report = {
            "analysis_config": settings.analysis.model_dump(),
            "stable_region_config": settings.stable_regions.model_dump(),
            "tracks": rows,
        }
        text = json.dumps(report, indent=2, allow_nan=False)
        if args.output:
            if args.output.exists():
                parser.error(f"output exists: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n")
        print(text)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
