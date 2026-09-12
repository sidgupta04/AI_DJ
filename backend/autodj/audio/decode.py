"""Decode boundary.

DSP never operates on "MP3 data": ffmpeg turns a compressed file into float PCM, and everything
above this module works on numpy arrays. Source files are read-only inputs and are never modified.

This is the one module in ``autodj.audio`` that performs I/O; the analysis modules above it stay
pure functions over arrays.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# Absolute paths are used everywhere, so a filename beginning with "-" can never be read as an
# option, and argument lists (never shells) mean spaces, quotes, parentheses and apostrophes in
# filenames need no escaping.


class SourceFailure(StrEnum):
    """Structured reasons an audio file cannot be used. Persisted in ``tracks.failure_reason``."""

    TOOL_MISSING = "TOOL_MISSING"
    TIMEOUT = "TIMEOUT"
    PROBE_FAILED = "PROBE_FAILED"
    UNREADABLE_PROBE_OUTPUT = "UNREADABLE_PROBE_OUTPUT"
    NO_AUDIO_STREAM = "NO_AUDIO_STREAM"
    INVALID_DURATION = "INVALID_DURATION"
    INVALID_SAMPLE_FORMAT = "INVALID_SAMPLE_FORMAT"
    TOO_SHORT = "TOO_SHORT"
    DECODE_FAILED = "DECODE_FAILED"
    EMPTY_AUDIO = "EMPTY_AUDIO"
    NON_FINITE_SAMPLES = "NON_FINITE_SAMPLES"
    SILENT_AUDIO = "SILENT_AUDIO"


class SourceError(Exception):
    """A file-level failure with a machine-readable reason and a human-readable detail."""

    def __init__(self, failure: SourceFailure, detail: str) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"reason": str(self.failure), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    duration_seconds: float
    sample_rate: int
    channels: int
    codec_name: str
    bit_rate: int | None
    tags: Mapping[str, str]


def _run(command: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise SourceError(SourceFailure.TOOL_MISSING, f"{command[0]} not found on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise SourceError(SourceFailure.TIMEOUT, f"{command[0]} exceeded {timeout:g}s") from error


def _stderr_tail(process: subprocess.CompletedProcess[bytes], limit: int = 400) -> str:
    text = process.stderr.decode("utf-8", errors="replace").strip()
    collapsed = " ".join(text.split())
    return collapsed[-limit:] if collapsed else f"exit code {process.returncode}"


def _lowercase_tags(*tag_maps: Any) -> dict[str, str]:
    tags: dict[str, str] = {}
    for tag_map in tag_maps:
        if not isinstance(tag_map, dict):
            continue
        for key, value in tag_map.items():
            if isinstance(key, str) and isinstance(value, str):
                tags.setdefault(key.strip().lower(), value)
    return tags


def probe_source(path: Path, *, timeout: float = 120.0) -> SourceMetadata:
    """Read container and stream metadata, including embedded tags, without decoding audio."""
    command = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    process = _run(command, timeout=timeout)
    if process.returncode != 0:
        raise SourceError(SourceFailure.PROBE_FAILED, _stderr_tail(process))

    try:
        payload = json.loads(process.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise SourceError(SourceFailure.UNREADABLE_PROBE_OUTPUT, str(error)) from error

    streams = payload.get("streams") or []
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise SourceError(SourceFailure.NO_AUDIO_STREAM, "no audio stream in container")
    stream = audio_streams[0]
    container = payload.get("format") or {}

    duration = _parse_duration(stream.get("duration"), container.get("duration"))
    sample_rate = _parse_positive_int(stream.get("sample_rate"))
    channels = _parse_positive_int(stream.get("channels"))
    if sample_rate is None or channels is None:
        raise SourceError(
            SourceFailure.INVALID_SAMPLE_FORMAT,
            f"sample_rate={stream.get('sample_rate')!r} channels={stream.get('channels')!r}",
        )

    return SourceMetadata(
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        codec_name=str(stream.get("codec_name") or "unknown"),
        bit_rate=_parse_positive_int(container.get("bit_rate") or stream.get("bit_rate")),
        tags=_lowercase_tags(container.get("tags"), stream.get("tags")),
    )


def _parse_duration(*candidates: Any) -> float:
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if np.isfinite(duration) and duration > 0:
            return duration
    raise SourceError(SourceFailure.INVALID_DURATION, f"unusable duration {candidates!r}")


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def decode_to_mono(
    path: Path,
    *,
    sample_rate: int,
    max_seconds: float | None = None,
    timeout: float = 120.0,
) -> np.ndarray:
    """Decode to mono float32 PCM at ``sample_rate``, optionally only the first seconds."""
    command = [
        FFMPEG,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
    ]
    if max_seconds is not None:
        command += ["-t", f"{max_seconds:g}"]
    command += ["-f", "f32le", "-"]

    process = _run(command, timeout=timeout)
    if process.returncode != 0:
        raise SourceError(SourceFailure.DECODE_FAILED, _stderr_tail(process))

    samples = np.frombuffer(process.stdout, dtype="<f4").astype(np.float32, copy=True)
    if samples.size == 0:
        raise SourceError(SourceFailure.EMPTY_AUDIO, "decoder produced no samples")
    if not bool(np.isfinite(samples).all()):
        raise SourceError(SourceFailure.NON_FINITE_SAMPLES, "decoded audio contains NaN or Inf")
    return samples
