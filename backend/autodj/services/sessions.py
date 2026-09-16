"""M7 synchronous pre-render orchestration; never performs offline analysis."""

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.decode import decode_to_pcm
from autodj.config.settings import Settings
from autodj.dj.plan import plan_transition
from autodj.dj.rank import rank_candidates
from autodj.dj.retrieve import retrieve_candidates
from autodj.dj.types import RegionInfo, TrackCandidate
from autodj.persistence.database import build_engine, build_session_factory, session_scope
from autodj.persistence.repositories import TrackRepository
from autodj.persistence.session_repository import SessionRepository
from autodj.render.align import alignment_beat_index
from autodj.render.session import append_transition
from autodj.render.stretch import STRETCH_BOUND_ATOL, build_stretcher
from autodj.render.write import apply_clip_protection, write_pcm16_wav
from autodj.services.selection import candidate_from_row


class SessionService:
    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.factory = factory

    def library(self) -> tuple[list[TrackCandidate], dict[int, dict[str, Any]]]:
        with session_scope(self.factory) as session:
            repo = TrackRepository(session)
            candidates = [
                candidate_from_row(r)
                for r in repo.list_candidates(analysis_version=self.settings.analysis.version)
            ]
            labels = {t.id: {"title": t.title, "artist": t.artist} for t in repo.list_tracks()}
        return candidates, labels

    def tracks(self) -> dict[str, Any]:
        tracks, labels = self.library()
        return {
            "tracks": [
                {"id": t.track_id, **labels[t.track_id], "native_bpm": t.native_bpm} for t in tracks
            ],
            "default_length": self.settings.session.default_length,
            "max_length": self.settings.session.max_length,
        }

    def get(self, identifier: str) -> dict[str, Any] | None:
        with session_scope(self.factory) as session:
            row = SessionRepository(session).get(identifier)
            return dict(row.payload) if row else None

    def audio_path(self, identifier: str) -> Path:
        return self.settings.render_cache_dir / "sessions" / f"{identifier}.wav"

    def _save(self, record: dict[str, Any]) -> None:
        config = self.settings.snapshot()
        config.pop("database_url", None)
        with session_scope(self.factory) as session:
            SessionRepository(session).save(record, config)

    def create(self, seed_track_id: int, length: int | None = None) -> dict[str, Any]:
        cfg = self.settings
        length = cfg.session.default_length if length is None else length
        if not 2 <= length <= cfg.session.max_length:
            raise ValueError(f"length must be between 2 and {cfg.session.max_length}")
        if cfg.session.selection_strategy != "greedy":
            raise ValueError("M7 sessions support the greedy strategy only")
        candidates, labels = self.library()
        seed = next((t for t in candidates if t.track_id == seed_track_id), None)
        if seed is None:
            raise ValueError("seed must be a COMPLETE current-version track")
        record: dict[str, Any] = {
            "id": str(uuid4()),
            "status": "RENDERING",
            "seed_track_id": seed_track_id,
            "requested_length": length,
            "session_bpm": seed.native_bpm,
            "tracks": [],
            "transitions": [],
            "failure": None,
            "stop_reason": None,
            "duration_seconds": None,
            "audio_url": None,
        }
        self._save(record)
        destination = self.audio_path(record["id"])
        try:
            self._render(record, seed, candidates, labels, destination)
        except Exception as error:
            destination.unlink(missing_ok=True)
            record.update(
                status="FAILED",
                audio_url=None,
                failure={
                    "reason": str(getattr(error, "failure", type(error).__name__)),
                    "detail": str(error),
                },
            )
        try:
            self._save(record)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return record

    def _render(
        self,
        record: dict[str, Any],
        seed: TrackCandidate,
        candidates: list[TrackCandidate],
        labels: dict[int, dict[str, Any]],
        destination: Path,
    ) -> None:
        cfg = self.settings
        bpm, rate = seed.native_bpm, cfg.render.sample_rate
        fade = round(cfg.transition.crossfade_beats * 60 / bpm * rate)
        stretcher = build_stretcher(cfg.tempo.stretch_backend)

        def prepare(track: TrackCandidate) -> np.ndarray:
            ratio = bpm / track.native_bpm
            if not (
                cfg.tempo.min_stretch_ratio - STRETCH_BOUND_ATOL
                <= ratio
                <= cfg.tempo.max_stretch_ratio + STRETCH_BOUND_ATOL
            ):
                raise ValueError("STRETCH_OUT_OF_BOUNDS")
            return stretcher.stretch(
                decode_to_pcm(
                    cfg.audio_library_dir / track.audio_path,
                    sample_rate=rate,
                    channels=cfg.render.channels,
                    timeout=cfg.ingestion.subprocess_timeout_seconds,
                ),
                stretch_ratio=ratio,
                sample_rate=rate,
            )

        def beat_sample(track: TrackCandidate, region: RegionInfo) -> int:
            index = alignment_beat_index(
                region.start_beat,
                region.end_beat,
                len(track.beat_times),
                align_on_downbeat=cfg.transition.align_on_downbeat,
            )
            return round(track.beat_times[index] / (bpm / track.native_bpm) * rate)

        def item(track: TrackCandidate, start: int, end: int, entry: int) -> dict[str, Any]:
            return {
                "id": track.track_id,
                **labels[track.track_id],
                "native_bpm": track.native_bpm,
                "stretch_percent": 100 * (bpm / track.native_bpm - 1),
                "start_seconds": start / rate,
                "end_seconds": end / rate,
                "source_entry_seconds": entry / rate * (bpm / track.native_bpm),
            }

        current, played = seed, {seed.track_id}
        mixed = prepare(seed)
        offset = earliest = 0
        record["tracks"].append(item(seed, 0, len(mixed), 0))
        while len(played) < record["requested_length"]:
            pool = retrieve_candidates(
                current,
                candidates,
                played,
                session_bpm=bpm,
                min_stretch_ratio=cfg.tempo.min_stretch_ratio,
                max_stretch_ratio=cfg.tempo.max_stretch_ratio,
                max_energy_delta=cfg.retrieval.max_energy_delta,
                energy_filter_enabled=cfg.retrieval.energy_filter_enabled,
                require_stable_region=True,
                allow_repeats=False,
            )
            ranked = rank_candidates(
                current,
                pool,
                session_bpm=bpm,
                min_stretch_ratio=cfg.tempo.min_stretch_ratio,
                max_stretch_ratio=cfg.tempo.max_stretch_ratio,
                weight_tempo=cfg.ranking.weight_tempo,
                weight_energy=cfg.ranking.weight_energy,
                weight_quality=cfg.ranking.weight_quality,
            )
            outgoing = replace(
                current,
                stable_regions=[
                    r
                    for r in current.stable_regions
                    if beat_sample(current, r) + offset >= earliest
                    and beat_sample(current, r) + offset + fade <= len(mixed)
                ],
            )
            chosen = None
            for ranked_track in ranked:
                next_track = ranked_track.candidate
                chosen = plan_transition(
                    outgoing,
                    next_track,
                    session_bpm=bpm,
                    min_stretch_ratio=cfg.tempo.min_stretch_ratio,
                    max_stretch_ratio=cfg.tempo.max_stretch_ratio,
                    outgoing_search_fraction=cfg.transition.outgoing_search_fraction,
                    incoming_search_fraction=cfg.transition.incoming_search_fraction,
                    weight_stability=cfg.transition.weight_stability,
                    weight_energy=cfg.transition.weight_energy,
                    weight_stretch=cfg.transition.weight_stretch,
                    weight_position=cfg.transition.weight_position,
                )
                if chosen is not None:
                    break
            if chosen is None:
                record["stop_reason"] = "NO_COMPATIBLE_TRANSITION"
                break
            incoming = prepare(next_track)
            exit_sample = offset + beat_sample(current, chosen.outgoing_region)
            entry = beat_sample(next_track, chosen.incoming_region)
            mixed = append_transition(
                mixed,
                incoming,
                exit_sample=exit_sample,
                entry_sample=entry,
                fade_frames=fade,
                earliest_exit=earliest,
            )
            record["tracks"][-1]["end_seconds"] = (exit_sample + fade) / rate
            record["transitions"].append(
                {
                    **asdict(chosen),
                    "start_seconds": exit_sample / rate,
                    "end_seconds": (exit_sample + fade) / rate,
                    "outgoing_source_seconds": (exit_sample - offset)
                    / rate
                    * (bpm / current.native_bpm),
                    "incoming_source_seconds": entry / rate * (bpm / next_track.native_bpm),
                }
            )
            record["tracks"].append(item(next_track, exit_sample, len(mixed), entry))
            offset, earliest = exit_sample - entry, exit_sample + fade
            current = next_track
            played.add(current.track_id)
        if not record["transitions"]:
            raise ValueError("NO_COMPATIBLE_TRANSITION: no two-track mix could be planned")
        protected, peak, exceeded, clipped = apply_clip_protection(
            mixed, peak_ceiling_dbfs=cfg.render.peak_ceiling_dbfs
        )
        write_pcm16_wav(destination, protected, sample_rate=rate)
        record.update(
            status="PARTIAL" if record["stop_reason"] else "READY",
            duration_seconds=len(mixed) / rate,
            peak_dbfs=peak,
            peak_exceeded=exceeded,
            clipped=clipped,
            audio_url=f"/sessions/{record['id']}/audio",
        )


def open_session_service(settings: Settings) -> tuple[SessionService, Engine]:
    """Resource construction stays inside services; caller disposes the returned engine."""
    engine = build_engine(settings)
    return SessionService(settings, build_session_factory(engine)), engine
