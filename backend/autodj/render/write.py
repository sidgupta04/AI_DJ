"""WAV writing and peak / clip measurement.

The mix writer is the I/O boundary of ``autodj.render``: arrays in, a 16-bit
PCM file out. Source library files are never touched.
"""

from __future__ import annotations

import math
import os
import wave
from pathlib import Path

import numpy as np

SILENCE_DBFS = -120.0


def ensure_channel_layout(audio: np.ndarray, channels: int) -> np.ndarray:
    """Return float32 audio as ``(n_samples, channels)``, duplicating mono if needed."""
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        array = array[:, np.newaxis]
    elif array.ndim == 2 and array.shape[0] <= 8 and array.shape[1] > array.shape[0]:
        array = array.T
    if array.ndim != 2:
        raise ValueError(f"audio must be 1-D or 2-D, got shape {array.shape}")
    if array.shape[1] == channels:
        return np.ascontiguousarray(array, dtype=np.float32)
    if array.shape[1] == 1 and channels > 1:
        return np.repeat(array, channels, axis=1)
    if array.shape[1] > channels:
        return np.ascontiguousarray(array[:, :channels], dtype=np.float32)
    raise ValueError(f"cannot convert {array.shape[1]} channels to {channels}")


def peak_dbfs(audio: np.ndarray) -> float:
    """Peak level in dBFS. Silence maps to ``SILENCE_DBFS`` rather than -inf."""
    if audio.size == 0:
        return SILENCE_DBFS
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return SILENCE_DBFS
    return max(SILENCE_DBFS, 20.0 * math.log10(peak))


def apply_clip_protection(
    audio: np.ndarray,
    *,
    peak_ceiling_dbfs: float,
) -> tuple[np.ndarray, float, bool, bool]:
    """Scale peaks above 1.0 into range. Returns audio, peak_dbfs, exceeded, clipped.

    ``peak_dbfs`` and the flags describe the *unprotected* mix. Equal-power fades
    already limit summing gain; this step only prevents int16 wrap.
    """
    measured = peak_dbfs(audio)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    clipped = peak > 1.0
    exceeded = measured > peak_ceiling_dbfs
    protected = np.array(audio, copy=True, dtype=np.float32)
    if peak > 1.0:
        protected = (protected / peak).astype(np.float32, copy=False)
    return protected, measured, exceeded, clipped


def write_pcm16_wav(path: Path, audio: np.ndarray, *, sample_rate: int) -> None:
    """Write ``audio`` as little-endian 16-bit PCM WAV. ``audio`` is ``(n, c)``.

    Writes a sibling ``.tmp`` file first and replaces ``path`` only after the
    WAV is complete, so a crash cannot leave a truncated file at ``path``.
    """
    if audio.ndim != 2:
        raise ValueError(f"expected (n_samples, channels), got {audio.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _write_pcm16_wav(tmp_path, audio, sample_rate=sample_rate)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_pcm16_wav(path: Path, audio: np.ndarray, *, sample_rate: int) -> None:
    pcm = np.clip(np.round(audio * 32767.0), -32768, 32767).astype("<i2")
    interleaved = np.ascontiguousarray(pcm).reshape(-1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(int(audio.shape[1]))
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(interleaved.tobytes())
