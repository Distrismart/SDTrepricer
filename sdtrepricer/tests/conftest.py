from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sdtrepricer.app.models import Base

collect_ignore = ["../app/services/test_data.py", "../app/api/test_data.py"]
collect_ignore_glob = ["../app/services/test_*.py", "../app/api/test_*.py"]


class AsyncSessionWrapper:
    """Minimal async wrapper around a synchronous SQLAlchemy session."""

    def __init__(self, sync_session: Session) -> None:
        self._session = sync_session

    def add(self, obj) -> None:
        self._session.add(obj)

    def add_all(self, objects) -> None:
        self._session.add_all(objects)

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self._session.scalar(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        return self._session.scalars(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def flush(self) -> None:
        self._session.flush()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance) -> None:
        self._session.refresh(instance)

    async def close(self) -> None:
        self._session.close()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSessionWrapper]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield AsyncSessionWrapper(session)
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
