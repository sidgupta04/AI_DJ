"""Track persistence.

Ingestion is re-runnable: a file is identified by its library-relative path, so re-scanning
updates the existing row instead of inserting a duplicate. ``content_hash`` answers only "did
these bytes change since the last scan"; it never merges rows, so two paths holding the same audio
remain two tracks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from autodj.audio.beats import BeatAnalysis
from autodj.audio.decode import SourceMetadata
from autodj.audio.naming import TrackNaming
from autodj.persistence.models import AnalysisStatus, Track, TrackAnalysis


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

    def save_analysis(self, track: Track, result: BeatAnalysis, *, version: int) -> TrackAnalysis:
        track.native_bpm = result.native_bpm
        track.analysis_confidence = result.confidence
        track.analysis_version = version
        track.analysis_status = AnalysisStatus.COMPLETE
        track.failure_reason = None

        row = self.get_analysis(track.id)
        if row is None:
            row = TrackAnalysis(track_id=track.id)
            self._session.add(row)

        beat_times = [round(float(time), 6) for time in result.beat_times]
        row.beat_times = beat_times
        row.beat_count = len(beat_times)
        row.sample_rate = result.sample_rate
        row.hop_length = result.hop_length
        row.refine_hop_length = result.refine_hop_length
        row.median_ibi_seconds = 60.0 / result.native_bpm
        row.ibi_cv = result.ibi_cv
        row.onset_contrast = result.onset_contrast
        row.tempo_octave_factor = result.tempo_octave_factor
        self._session.flush()
        return row

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
        if track.id is None:
            return
        existing = self.get_analysis(track.id)
        if existing is not None:
            self._session.delete(existing)
