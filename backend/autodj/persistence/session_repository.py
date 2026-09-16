"""Persistence boundary for the M7 session snapshot."""

from typing import Any

from sqlalchemy.orm import Session

from autodj.persistence.models import DJSession


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, identifier: str) -> DJSession | None:
        return self.session.get(DJSession, identifier)

    def save(self, payload: dict[str, Any], config: dict[str, Any]) -> None:
        row = self.get(payload["id"])
        if row is None:
            row = DJSession(id=payload["id"], config_snapshot=config)
            self.session.add(row)
        row.status = payload["status"]
        row.payload = dict(payload)
        self.session.flush()
