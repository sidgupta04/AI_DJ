"""Candidate loading excludes incomplete, stale, failed, and featureless rows."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.naming import MetadataSource
from autodj.config.settings import Settings
from autodj.persistence.models import AnalysisStatus, Track, TrackAnalysis
from autodj.persistence.repositories import TrackRepository


def _region() -> dict[str, float | int]:
    return {
        "start_beat": 4,
        "end_beat": 36,
        "start_time": 10.0,
        "end_time": 30.0,
        "score": 0.8,
        "ibi_cv": 0.02,
        "in_tolerance_fraction": 1.0,
        "mean_onset": 0.7,
        "mean_energy": 0.5,
    }


def _add_track(
    session: Session,
    *,
    path: str,
    status: AnalysisStatus,
    version: int | None,
    bpm: float | None = 124.0,
    energy: float | None = 0.5,
    confidence: float | None = 0.8,
    duration: float | None = 180.0,
    with_analysis: bool = True,
    regions: list[dict[str, float | int]] | None = None,
) -> Track:
    track = Track(
        audio_path=path,
        content_hash="a" * 64,
        title=path,
        artist=None,
        metadata_source=MetadataSource.FILENAME,
        duration_seconds=duration,
        analysis_status=status,
        native_bpm=bpm,
        analysis_confidence=confidence,
        analysis_version=version,
        energy=energy,
    )
    session.add(track)
    session.flush()
    if with_analysis:
        session.add(
            TrackAnalysis(
                track_id=track.id,
                beat_times=[0.0, 0.5],
                beat_count=2,
                sample_rate=22050,
                hop_length=512,
                refine_hop_length=256,
                median_ibi_seconds=0.5,
                ibi_cv=0.01,
                onset_contrast=0.8,
                tempo_octave_factor=1.0,
                energy_curve=[0.5],
                energy_curve_hz=10.0,
                energy_scalar=energy if energy is not None else 0.0,
                stable_regions=regions if regions is not None else [_region()],
            )
        )
    return track


def test_list_candidates_keeps_only_current_complete_featureful_rows(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    with session_factory() as session:
        keep = _add_track(
            session,
            path="keep.wav",
            status=AnalysisStatus.COMPLETE,
            version=settings.analysis.version,
        )
        _add_track(
            session,
            path="pending.wav",
            status=AnalysisStatus.PENDING,
            version=None,
            with_analysis=False,
        )
        _add_track(
            session,
            path="failed.wav",
            status=AnalysisStatus.FAILED,
            version=None,
            with_analysis=False,
        )
        _add_track(
            session,
            path="stale.wav",
            status=AnalysisStatus.COMPLETE,
            version=settings.analysis.version - 1,
        )
        _add_track(
            session,
            path="incomplete.wav",
            status=AnalysisStatus.COMPLETE,
            version=settings.analysis.version,
            bpm=None,
            energy=None,
        )
        session.commit()
        keep_id = keep.id

    with session_factory() as session:
        rows = TrackRepository(session).list_candidates(analysis_version=settings.analysis.version)

    assert [row["track_id"] for row in rows] == [keep_id]
    assert rows[0]["native_bpm"] == 124.0
    assert rows[0]["stable_regions"]
