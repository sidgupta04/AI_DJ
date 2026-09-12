"""SQLAlchemy declarative base.

Tables are introduced by the milestone that needs them, each with its own Alembic revision,
so the schema and the code that uses it always land together.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
