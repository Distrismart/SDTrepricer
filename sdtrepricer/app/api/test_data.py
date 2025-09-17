"""Endpoints for uploading local test datasets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..services.test_data import ingest_competitor_data, ingest_floor_data

router = APIRouter()


@router.post("/floor")
async def upload_floor_dataset(
    marketplace_code: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    content = await file.read()
    try:
        count = await ingest_floor_data(session, marketplace_code, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"records": count}


@router.post("/competitors")
async def upload_competitor_dataset(
    marketplace_code: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    content = await file.read()
    try:
        count = await ingest_competitor_data(session, marketplace_code, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"records": count}


__all__ = ["router"]
