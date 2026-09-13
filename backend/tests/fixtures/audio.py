"""Synthetic audio fixtures.

The real library is local-only and never available to automated tests, so tests build their own
files: a tone rendered to WAV with the standard library, optionally encoded to MP3 with ffmpeg and
tagged, plus deliberately broken files.
"""

from __future__ import annotations

import subprocess
import wave
from collections.abc import Mapping
from pathlib import Path

import numpy as np

DEFAULT_SAMPLE_RATE = 22050


def click_track(
    bpm: float,
    *,
    seconds: float = 16.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    click_samples: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """A decaying impulse on every beat, plus the ground-truth beat times."""
    frame_count = int(seconds * sample_rate)
    signal = np.zeros(frame_count, dtype=np.float32)
    interval = 60.0 / bpm
    beat_times = np.arange(0.0, seconds, interval, dtype=np.float64)
    click = np.linspace(1.0, 0.0, click_samples, dtype=np.float32)
    for time in beat_times:
        start = int(round(time * sample_rate))
        if start >= frame_count:
            continue
        end = min(start + click_samples, frame_count)
        signal[start:end] = click[: end - start]
    return signal, beat_times[beat_times < seconds]


def write_click_wav(
    path: Path,
    *,
    bpm: float,
    seconds: float = 16.0,
    sample_rate: int = 44100,
) -> tuple[Path, np.ndarray]:
    signal, beat_times = click_track(bpm, seconds=seconds, sample_rate=sample_rate)
    pcm = np.clip(signal * 32767.0, -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path, beat_times


def write_noise_wav(
    path: Path,
    *,
    seconds: float = 16.0,
    sample_rate: int = 44100,
    seed: int = 0,
) -> Path:
    generator = np.random.default_rng(seed)
    signal = (0.3 * generator.standard_normal(int(seconds * sample_rate))).astype(np.float32)
    pcm = np.clip(signal * 32767.0, -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def write_wav(
    path: Path,
    *,
    seconds: float = 2.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    frequency: float = 220.0,
    amplitude: float = 0.3,
    channels: int = 1,
    silent: bool = False,
    silence_lead_seconds: float = 0.0,
) -> Path:
    frame_count = int(seconds * sample_rate)
    times = np.arange(frame_count, dtype=np.float64) / sample_rate
    signal = np.zeros(frame_count) if silent else amplitude * np.sin(2 * np.pi * frequency * times)
    signal[: int(silence_lead_seconds * sample_rate)] = 0.0
    pcm = np.clip(signal * 32767.0, -32768, 32767).astype("<i2")
    if channels == 2:
        pcm = np.repeat(pcm[:, None], 2, axis=1).reshape(-1)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def encode_mp3(
    source: Path,
    destination: Path,
    *,
    tags: Mapping[str, str] | None = None,
    bitrate: str = "96k",
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
    for key, value in (tags or {}).items():
        command += ["-metadata", f"{key}={value}"]
    command += ["-codec:a", "libmp3lame", "-b:a", bitrate, str(destination)]
    subprocess.run(command, check=True, capture_output=True)
    return destination


def make_mp3(
    directory: Path,
    filename: str,
    *,
    seconds: float = 2.0,
    tags: Mapping[str, str] | None = None,
    frequency: float = 220.0,
    silent: bool = False,
    silence_lead_seconds: float = 0.0,
) -> Path:
    """Write ``directory/filename`` as a real MP3, keeping the caller's exact filename."""
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / ".staging.wav"
    write_wav(
        staging,
        seconds=seconds,
        frequency=frequency,
        silent=silent,
        silence_lead_seconds=silence_lead_seconds,
    )
    try:
        return encode_mp3(staging, directory / filename, tags=tags)
    finally:
        staging.unlink(missing_ok=True)


def write_corrupt_mp3(path: Path, *, size: int = 4096) -> Path:
    """Bytes with an MP3-ish header that no decoder can turn into audio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    generator = np.random.default_rng(seed=17)
    payload = (
        b"ID3\x03\x00\x00\x00\x00\x00\x00"
        + generator.integers(0, 256, size=size, dtype=np.uint8).tobytes()
    )
    path.write_bytes(payload)
    return path


def write_empty_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def write_text_file(path: Path, text: str = "this is not audio\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
