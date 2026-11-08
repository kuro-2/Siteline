"""Postgres access (psycopg 3). Plain SQL; the schema lives in supabase/migrations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from engine.settings import get_settings

_pool: ConnectionPool | None = None


def _dsn() -> str:
    return get_settings().require("database_url", "The engine and API need the Supabase database.")


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # prepare_threshold=None: Supabase's transaction pooler does not support
        # server-side prepared statements.
        _pool = ConnectionPool(
            _dsn(),
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": False},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connect() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """A pooled connection inside a transaction; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn
