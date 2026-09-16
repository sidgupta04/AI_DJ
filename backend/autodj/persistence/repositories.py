"""Track persistence.

Ingestion is re-runnable: a file is identified by its library-relative path, so re-scanning
updates the existing row instead of inserting a duplicate. ``content_hash`` answers only "did
these bytes change since the last scan"; it never merges rows, so two paths holding the same audio
remain two tracks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from autodj.audio.beats import BeatAnalysis
from autodj.audio.decode import SourceMetadata
from autodj.audio.energy import EnergyAnalysis
from autodj.audio.naming import TrackNaming
from autodj.audio.regions import StableRegion
from autodj.persistence.models import (
    AnalysisStatus,
    Track,
    TrackAnalysis,
    Transition,
    TransitionStatus,
)


class TrackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, track_id: int) -> Track | None:
        return self._session.get(Track, track_id)

    def get_by_path(self, audio_path: str) -> Track | None:
        """The one row for a library-relative path, the only lookup that identifies a track."""
        return self._session.scalar(select(Track).where(Track.audio_path == audio_path))

    def get_analysis(self, track_id: int) -> TrackAnalysis | None:
        return self._session.scalar(select(TrackAnalysis).where(TrackAnalysis.track_id == track_id))

    def list_by_content_hash(self, content_hash: str) -> list[Track]:
        """Every row whose bytes match.

        Plural by design: a hash can name several tracks, because identical audio filed under two
        paths is two tracks. Nothing in ingestion resolves a file through this.
        """
        statement = select(Track).where(Track.content_hash == content_hash).order_by(Track.id)
        return list(self._session.scalars(statement))

    def list_tracks(
        self,
        *,
        statuses: Sequence[AnalysisStatus] | None = None,
        limit: int | None = None,
    ) -> list[Track]:
        statement = select(Track).order_by(Track.audio_path)
        if statuses:
            statement = statement.where(Track.analysis_status.in_(statuses))
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.scalars(statement))

    def counts_by_status(self) -> dict[AnalysisStatus, int]:
        rows = self._session.execute(
            select(Track.analysis_status, func.count()).group_by(Track.analysis_status)
        )
        return {status: count for status, count in rows}

    def list_candidates(self, *, analysis_version: int) -> list[dict[str, object]]:
        """COMPLETE tracks at ``analysis_version`` with features for candidate selection.

        Returns dicts rather than ORM models so the caller can construct pure
        dataclasses without importing persistence types.  Each dict contains the
        track-level columns needed for retrieval and ranking plus the temporal
        features from ``track_analysis`` that planning consumes.
        """
        statement = (
            select(Track, TrackAnalysis)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                Track.analysis_status == AnalysisStatus.COMPLETE,
                Track.analysis_version == analysis_version,
            )
            .order_by(Track.id)
        )
        results: list[dict[str, object]] = []
        for track, analysis in self._session.execute(statement):
            if (
                track.native_bpm is None
                or track.energy is None
                or track.analysis_confidence is None
                or track.duration_seconds is None
            ):
                continue
            results.append(
                {
                    "track_id": track.id,
                    "audio_path": track.audio_path,
                    "native_bpm": track.native_bpm,
                    "energy": track.energy,
                    "analysis_confidence": track.analysis_confidence,
                    "analysis_version": track.analysis_version,
                    "duration_seconds": track.duration_seconds,
                    "stable_regions": analysis.stable_regions,
                    "beat_times": analysis.beat_times,
                    "beat_count": analysis.beat_count,
                }
            )
        return results

    def save_source(
        self,
        *,
        audio_path: str,
        content_hash: str,
        naming: TrackNaming,
        metadata: SourceMetadata,
    ) -> tuple[Track, bool]:
        """Record a usable file as PENDING analysis. Returns the row and whether it is new."""
        track = self.get_by_path(audio_path)
        created = track is None
        if track is None:
            track = Track(audio_path=audio_path)
            self._session.add(track)

        track.content_hash = content_hash
        track.title = naming.title
        track.artist = naming.artist
        track.metadata_source = naming.source
        track.duration_seconds = metadata.duration_seconds
        track.native_sample_rate = metadata.sample_rate
        track.channels = metadata.channels
        track.codec_name = metadata.codec_name
        track.bit_rate = metadata.bit_rate
        track.analysis_status = AnalysisStatus.PENDING
        track.failure_reason = None
        self._clear_analysis_fields(track)

        self._session.flush()
        return track, created

    def save_failure(
        self,
        *,
        audio_path: str,
        content_hash: str | None,
        naming: TrackNaming,
        failure: Mapping[str, str],
    ) -> tuple[Track, bool]:
        """Record an unusable file as FAILED with a structured reason, never raising."""
        track = self.get_by_path(audio_path)
        created = track is None
        if track is None:
            track = Track(audio_path=audio_path)
            self._session.add(track)

        if content_hash is not None:
            track.content_hash = content_hash
        elif track.content_hash is None:
            track.content_hash = ""

        track.title = naming.title
        track.artist = naming.artist
        track.metadata_source = naming.source
        track.analysis_status = AnalysisStatus.FAILED
        track.failure_reason = dict(failure)
        self._clear_analysis_fields(track)

        self._session.flush()
        return track, created

    def list_for_analysis(
        self,
        *,
        analysis_version: int,
        reanalyze: bool = False,
        audio_path: str | None = None,
        limit: int | None = None,
    ) -> list[Track]:
        """Tracks that should be analysed, in a deterministic path order.

        The default queue is PENDING, PROCESSING (a previous run that died mid-file),
        and COMPLETE rows whose stored ``analysis_version`` is stale. ``reanalyze``
        adds current COMPLETE and FAILED rows.
        """
        statement = select(Track).order_by(Track.audio_path)
        if audio_path is not None:
            statement = statement.where(Track.audio_path == audio_path)
        elif not reanalyze:
            statement = statement.where(
                or_(
                    Track.analysis_status.in_((AnalysisStatus.PENDING, AnalysisStatus.PROCESSING)),
                    and_(
                        Track.analysis_status == AnalysisStatus.COMPLETE,
                        Track.analysis_version.is_distinct_from(analysis_version),
                    ),
                )
            )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.scalars(statement))

    def mark_processing(self, track: Track) -> None:
        track.analysis_status = AnalysisStatus.PROCESSING

    def save_analysis(
        self,
        track: Track,
        beats: BeatAnalysis,
        energy: EnergyAnalysis,
        regions: Sequence[StableRegion],
        *,
        version: int,
    ) -> TrackAnalysis:
        track.native_bpm = beats.native_bpm
        track.analysis_confidence = beats.confidence
        track.analysis_version = version
        track.energy = energy.scalar
        track.analysis_status = AnalysisStatus.COMPLETE
        track.failure_reason = None

        row = self.get_analysis(track.id)
        if row is None:
            row = TrackAnalysis(track_id=track.id)
            self._session.add(row)

        beat_times = [round(float(time), 6) for time in beats.beat_times]
        row.beat_times = beat_times
        row.beat_count = len(beat_times)
        row.sample_rate = beats.sample_rate
        row.hop_length = beats.hop_length
        row.refine_hop_length = beats.refine_hop_length
        row.median_ibi_seconds = 60.0 / beats.native_bpm
        row.ibi_cv = beats.ibi_cv
        row.onset_contrast = beats.onset_contrast
        row.tempo_octave_factor = beats.tempo_octave_factor
        row.energy_curve = [round(float(value), 6) for value in energy.curve]
        row.energy_curve_hz = energy.curve_hz
        row.energy_scalar = energy.scalar
        row.stable_regions = [region.as_dict() for region in regions]
        self._session.flush()
        return row

    def rescale_library_energy(
        self,
        *,
        low_percentile: float,
        high_percentile: float,
        analysis_version: int,
    ) -> None:
        """Map COMPLETE current-version scalars through the library 5th/95th span.

        Every eligible track is rewritten, including ones not in the current analysis
        invocation. A collapsed span (p5 == p95) leaves the unscaled scalar in place.
        """
        rows = list(
            self._session.scalars(
                select(TrackAnalysis)
                .join(Track)
                .where(
                    Track.analysis_status == AnalysisStatus.COMPLETE,
                    Track.analysis_version == analysis_version,
                )
            )
        )
        if not rows:
            return
        scalars = [row.energy_scalar for row in rows]
        low = _percentile(scalars, low_percentile)
        high = _percentile(scalars, high_percentile)
        span = high - low
        by_id = {row.track_id: row.energy_scalar for row in rows}
        tracks = list(
            self._session.scalars(
                select(Track).where(
                    Track.id.in_(by_id.keys()),
                    Track.analysis_status == AnalysisStatus.COMPLETE,
                    Track.analysis_version == analysis_version,
                )
            )
        )
        for track in tracks:
            scalar = by_id[track.id]
            if span <= 1e-12:
                track.energy = scalar
            else:
                track.energy = min(1.0, max(0.0, (scalar - low) / span))

    def save_analysis_failure(self, track: Track, failure: Mapping[str, str]) -> Track:
        track.analysis_status = AnalysisStatus.FAILED
        track.failure_reason = dict(failure)
        self._clear_analysis_fields(track)
        self._session.flush()
        return track

    def _clear_analysis_fields(self, track: Track) -> None:
        track.native_bpm = None
        track.analysis_confidence = None
        track.analysis_version = None
        track.energy = None
        if track.id is None:
            return
        existing = self.get_analysis(track.id)
        if existing is not None:
            self._session.delete(existing)


class TransitionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, transition_id: int) -> Transition | None:
        return self._session.get(Transition, transition_id)

    def attach_evaluation(self, row: Transition, metrics: Mapping[str, Any]) -> None:
        """Attach measured values plus provenance/reasons; no pure-layer imports."""
        for name in (
            "strategy",
            "bpm_delta",
            "stretch_percent_a",
            "stretch_percent_b",
            "alignment_error_ms",
            "alignment_correlation",
            "energy_discontinuity_db",
            "region_stability_a",
            "region_stability_b",
            "planning_seconds",
            "render_seconds",
            "measurement_seconds",
        ):
            setattr(row, name, metrics.get(name))
        row.evaluation = dict(metrics)
        self._session.flush()

    def save(
        self,
        *,
        track_a_id: int,
        track_b_id: int,
        session_bpm: float,
        stretch_ratio: float,
        outgoing_start_beat: int,
        outgoing_end_beat: int,
        incoming_start_beat: int,
        incoming_end_beat: int,
        pair_cost: float,
        stability_cost: float,
        energy_cost: float,
        stretch_cost: float,
        position_cost: float,
        status: TransitionStatus,
        config_snapshot: Mapping[str, object],
        wav_path: str | None = None,
        peak_dbfs: float | None = None,
        peak_exceeded: bool = False,
        clipped: bool = False,
        failure_reason: Mapping[str, str] | None = None,
    ) -> Transition:
        row = Transition(
            track_a_id=track_a_id,
            track_b_id=track_b_id,
            session_bpm=session_bpm,
            stretch_ratio=stretch_ratio,
            outgoing_start_beat=outgoing_start_beat,
            outgoing_end_beat=outgoing_end_beat,
            incoming_start_beat=incoming_start_beat,
            incoming_end_beat=incoming_end_beat,
            pair_cost=pair_cost,
            stability_cost=stability_cost,
            energy_cost=energy_cost,
            stretch_cost=stretch_cost,
            position_cost=position_cost,
            wav_path=wav_path,
            peak_dbfs=peak_dbfs,
            peak_exceeded=peak_exceeded,
            clipped=clipped,
            status=status,
            failure_reason=dict(failure_reason) if failure_reason is not None else None,
            config_snapshot=dict(config_snapshot),
        )
        self._session.add(row)
        self._session.flush()
        return row


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (percentile / 100.0) * (len(ordered) - 1)
    low_index = int(rank)
    high_index = min(low_index + 1, len(ordered) - 1)
    fraction = rank - low_index
    return float(ordered[low_index] * (1.0 - fraction) + ordered[high_index] * fraction)
