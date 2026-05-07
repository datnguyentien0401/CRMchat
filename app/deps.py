from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session


def get_db() -> Generator[Session, None, None]:
    """
    This dependency is overridden in app startup / tests.
    """
    raise RuntimeError("DB dependency not configured")

