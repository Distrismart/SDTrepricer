"""Manual operations for repricer."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db, get_sp_api_client
from ..models import Marketplace, PriceEvent, Sku
from ..schemas import BulkFeedUploadResponse, ManualPriceUpdate, ManualRepriceRequest
from ..services.sp_api import SPAPIClient

router = APIRouter()


@router.post("/manual-reprice")
async def manual_reprice(
    request: Request,
    payload: ManualRepriceRequest,
) -> dict[str, str]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    await scheduler.trigger_marketplace(payload.marketplace_code, reason="manual")
    return {"status": "scheduled"}


@router.post("/manual-price", response_model=ManualPriceUpdate)
async def manual_price_update(
    payload: ManualPriceUpdate,
    session: AsyncSession = Depends(get_db),
    client: SPAPIClient = Depends(get_sp_api_client),
) -> ManualPriceUpdate:
    marketplace = await session.scalar(select(Marketplace).where(Marketplace.code == payload.marketplace_code))
    if marketplace is None:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    sku = await session.scalar(
        select(Sku).where(Sku.marketplace_id == marketplace.id, Sku.sku == payload.sku)
    )
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    old_price = sku.last_updated_price
    old_business = sku.last_updated_business_price
    await client.submit_price_update(
        marketplace.amazon_id,
        sku.sku,
        float(payload.price),
        float(payload.business_price) if payload.business_price is not None else None,
    )
    sku.last_updated_price = payload.price
    sku.last_updated_business_price = payload.business_price
    sku.last_price_update = datetime.utcnow()
    session.add(
        PriceEvent(
            sku_id=sku.id,
            created_at=datetime.utcnow(),
            old_price=old_price,
            new_price=payload.price,
            old_business_price=old_business,
            new_business_price=payload.business_price,
            reason="manual",
            context={"source": "manual"},
        )
    )
    await session.commit()
    return payload


@router.post("/bulk-upload", response_model=BulkFeedUploadResponse)
async def bulk_upload(
    marketplace_code: str,
    file: UploadFile,
    client: SPAPIClient = Depends(get_sp_api_client),
) -> BulkFeedUploadResponse:
    content = await file.read()
    response = await client.submit_bulk_feed(content, file.content_type or "text/csv")
    return BulkFeedUploadResponse(
        feed_id=response.get("feedDocumentId", "unknown"),
        submitted_at=datetime.utcnow(),
        status=response.get("status", "SUBMITTED"),
    )
