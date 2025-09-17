from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sdtrepricer.app.models import Base

collect_ignore = ["../app/services/test_data.py", "../app/api/test_data.py"]
collect_ignore_glob = ["../app/services/test_*.py", "../app/api/test_*.py"]


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:  # type: ignore[call-arg]
        yield session
    await engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
