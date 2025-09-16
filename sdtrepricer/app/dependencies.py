"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from .core.database import get_session
from .services.ftp_loader import FTPFeedLoader
from .services.sp_api import SPAPIClient, create_sp_api_client


async def get_db() -> AsyncIterator:
    async with get_session() as session:
        yield session


async def get_sp_api_client() -> AsyncIterator[SPAPIClient]:
    client = await create_sp_api_client()
    try:
        yield client
    finally:
        await client.close()


def get_ftp_loader() -> FTPFeedLoader:
    return FTPFeedLoader()
