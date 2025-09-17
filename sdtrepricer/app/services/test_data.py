"""Helpers for uploading and retrieving local test datasets."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TestCompetitorOffer, TestFloorPrice
from .ftp_loader import FloorPriceRecord


@dataclass
class UploadedCompetitorOffer:
    """Internal representation of an uploaded competitor offer."""

    asin: str
    seller_id: str
    price: float
    is_buy_box: bool
    fulfillment_type: str


def _decode_csv(content: bytes) -> csv.DictReader:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Unable to decode file as UTF-8") from exc
    stream = StringIO(text)
    reader = csv.DictReader(stream)
    if reader.fieldnames is None:
        raise ValueError("CSV file is missing headers")
    return reader


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


async def ingest_floor_data(
    session: AsyncSession, marketplace_code: str, content: bytes
) -> int:
    """Replace uploaded floor price data for a marketplace."""

    reader = _decode_csv(content)
    required = {"SKU", "ASIN", "MIN_PRICE"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    code = marketplace_code.upper()
    await session.execute(delete(TestFloorPrice).where(TestFloorPrice.marketplace_code == code))
    count = 0
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        asin = (row.get("ASIN") or "").strip()
        if not sku or not asin:
            continue
        min_price_value = row.get("MIN_PRICE")
        if min_price_value in (None, ""):
            continue
        min_business_raw = row.get("MIN_BUSINESS_PRICE")
        min_business_price = (
            Decimal(str(min_business_raw))
            if min_business_raw not in (None, "")
            else None
        )
        session.add(
            TestFloorPrice(
                marketplace_code=code,
                sku=sku,
                asin=asin,
                min_price=Decimal(str(min_price_value)),
                min_business_price=min_business_price,
            )
        )
        count += 1
    await session.commit()
    return count


async def ingest_competitor_data(
    session: AsyncSession, marketplace_code: str, content: bytes
) -> int:
    """Replace uploaded competitor offer data for a marketplace."""

    reader = _decode_csv(content)
    required = {"ASIN", "SELLER_ID", "PRICE"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    code = marketplace_code.upper()
    await session.execute(
        delete(TestCompetitorOffer).where(TestCompetitorOffer.marketplace_code == code)
    )
    count = 0
    for row in reader:
        asin = (row.get("ASIN") or "").strip()
        seller_id = (row.get("SELLER_ID") or "").strip()
        price_raw = row.get("PRICE")
        if not asin or not seller_id or price_raw in (None, ""):
            continue
        is_buy_box = _parse_bool(row.get("IS_BUY_BOX"))
        fulfillment = (row.get("FULFILLMENT_TYPE") or "UNKNOWN").strip() or "UNKNOWN"
        session.add(
            TestCompetitorOffer(
                marketplace_code=code,
                asin=asin,
                seller_id=seller_id,
                price=Decimal(str(price_raw)),
                is_buy_box=is_buy_box,
                fulfillment_type=fulfillment,
            )
        )
        count += 1
    await session.commit()
    return count


async def load_floor_prices(
    session: AsyncSession, marketplace_code: str
) -> dict[str, FloorPriceRecord]:
    """Return uploaded floor prices keyed by SKU."""

    code = marketplace_code.upper()
    rows = (
        await session.execute(
            select(TestFloorPrice).where(TestFloorPrice.marketplace_code == code)
        )
    ).scalars()
    return {
        row.sku: FloorPriceRecord(
            sku=row.sku,
            asin=row.asin,
            min_price=float(row.min_price),
            min_business_price=
            float(row.min_business_price) if row.min_business_price is not None else None,
        )
        for row in rows
    }


async def load_competitor_offers(
    session: AsyncSession, marketplace_code: str
) -> dict[str, list[UploadedCompetitorOffer]]:
    """Return uploaded competitor offers keyed by ASIN."""

    code = marketplace_code.upper()
    rows = (
        await session.execute(
            select(TestCompetitorOffer).where(TestCompetitorOffer.marketplace_code == code)
        )
    ).scalars()
    offers: dict[str, list[UploadedCompetitorOffer]] = defaultdict(list)
    for row in rows:
        offers[row.asin].append(
            UploadedCompetitorOffer(
                asin=row.asin,
                seller_id=row.seller_id,
                price=float(row.price),
                is_buy_box=row.is_buy_box,
                fulfillment_type=row.fulfillment_type,
            )
        )
    return offers


__all__ = [
    "UploadedCompetitorOffer",
    "ingest_floor_data",
    "ingest_competitor_data",
    "load_floor_prices",
    "load_competitor_offers",
]
