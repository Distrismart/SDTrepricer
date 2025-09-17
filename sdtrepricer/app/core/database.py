"""Async database engine and session management."""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from ..models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Create (or reuse) the async engine."""

    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, creating if required."""

    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncSession:
    """Yield an async database session."""

    session_factory = get_session_factory()
    async with session_factory() as session:  # type: ignore[call-arg]
        yield session


async def init_db() -> None:
    """Create database schema if it does not exist."""

    engine = get_engine()
    async with engine.begin() as conn:  # type: ignore[arg-type]
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_repricing_profile_migration)


def _apply_repricing_profile_migration(connection) -> None:
    """Backfill ``repricing_profile_id`` column for pre-existing ``skus`` tables."""

    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("skus")}
    if "repricing_profile_id" in columns:
        return

    connection.execute(text("ALTER TABLE skus ADD COLUMN repricing_profile_id INTEGER"))

    if connection.dialect.name == "sqlite":
        # SQLite cannot add foreign key constraints via ALTER TABLE; rely on
        # application-level integrity for in-memory fixtures.
        return

    connection.execute(
        text(
            "ALTER TABLE skus ADD CONSTRAINT fk_skus_repricing_profile_id "
            "FOREIGN KEY (repricing_profile_id) REFERENCES repricing_profiles(id) "
            "ON DELETE SET NULL"
        )
    )
