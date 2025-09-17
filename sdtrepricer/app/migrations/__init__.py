"""Simple data migrations executed at startup."""

from __future__ import annotations

from ..core.database import get_session
from .profile_defaults import ensure_default_profile_assignment


async def run_migrations() -> None:
    """Run idempotent migrations to keep data in sync with models."""

    async with get_session() as session:
        await ensure_default_profile_assignment(session)


__all__ = ["run_migrations"]
