"""Throwaway PostgreSQL databases for tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text


@contextmanager
def temporary_database(admin: Engine, prefix: str) -> Iterator[str]:
    """Create a database, yield its URL, and drop it again.

    ``admin`` must be an ``AUTOCOMMIT`` engine, because PostgreSQL refuses ``create database``
    inside a transaction.
    """
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with admin.connect() as connection:
        connection.execute(text(f'create database "{name}"'))
    try:
        yield admin.url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'drop database if exists "{name}" with (force)'))
