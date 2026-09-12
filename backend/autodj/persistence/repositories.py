"""Track persistence.

Ingestion is re-runnable: a file is identified by its library-relative path, so re-scanning
updates the existing row instead of inserting a duplicate. ``content_hash`` answers only "did
these bytes change since the last scan"; it never merges rows, so two paths holding the same audio
remain two tracks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autodj.audio.decode import SourceMetadata
from autodj.audio.naming import TrackNaming
from autodj.persistence.models import AnalysisStatus, Track


class TrackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_path(self, audio_path: str) -> Track | None:
        """The one row for a library-relative path, the only lookup that identifies a track."""
        return self._session.scalar(select(Track).where(Track.audio_path == audio_path))

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

        self._session.flush()
        return track, created
