"""API endpoints for repricing profile management."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..migrations.profile_defaults import DEFAULT_PROFILE_NAME
from ..models import Marketplace, RepricingProfile, Sku
from ..schemas import (
    ProfileAssignmentRequest,
    ProfileSkuSummary,
    RepricingProfileCreate,
    RepricingProfileDetail,
    RepricingProfileOut,
    RepricingProfileUpdate,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _to_schema(profile: RepricingProfile, sku_count: int) -> RepricingProfileOut:
    return RepricingProfileOut(
        id=profile.id,
        name=profile.name,
        frequency_minutes=profile.frequency_minutes,
        aggressiveness=profile.aggressiveness,
        price_change_limit_percent=float(profile.price_change_limit_percent),
        margin_policy=profile.margin_policy,
        step_up_percentage=float(profile.step_up_percentage),
        step_up_interval_hours=profile.step_up_interval_hours,
        sku_count=sku_count,
        created_at=profile.created_at,
    )


async def _get_profile(session: AsyncSession, profile_id: int) -> RepricingProfile:
    profile = await session.get(RepricingProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


async def _profile_detail(session: AsyncSession, profile: RepricingProfile) -> RepricingProfileDetail:
    sku_rows = (
        await session.execute(
            select(Sku, Marketplace.code)
            .join(Marketplace, Sku.marketplace_id == Marketplace.id)
            .where(Sku.profile_id == profile.id)
            .order_by(Sku.sku)
        )
    ).all()
    sku_count = len(sku_rows)
    return RepricingProfileDetail(
        **_to_schema(profile, sku_count).model_dump(),
        skus=[
            ProfileSkuSummary(
                id=sku.id,
                sku=sku.sku,
                asin=sku.asin,
                marketplace_code=code,
            )
            for sku, code in sku_rows
        ],
    )


@router.get("/", response_model=list[RepricingProfileOut])
async def list_profiles(session: AsyncSession = Depends(get_db)) -> list[RepricingProfileOut]:
    rows = (
        await session.execute(
            select(RepricingProfile, func.count(Sku.id))
            .outerjoin(Sku)
            .group_by(RepricingProfile.id)
            .order_by(RepricingProfile.name)
        )
    ).all()
    return [_to_schema(profile, int(count)) for profile, count in rows]


@router.post("/", response_model=RepricingProfileOut, status_code=201)
async def create_profile(
    payload: RepricingProfileCreate,
    session: AsyncSession = Depends(get_db),
) -> RepricingProfileOut:
    existing = await session.scalar(
        select(RepricingProfile).where(RepricingProfile.name == payload.name)
    )
    if existing:
        raise HTTPException(status_code=400, detail="Profile name already exists")
    profile = RepricingProfile(
        name=payload.name,
        frequency_minutes=payload.frequency_minutes,
        aggressiveness=payload.aggressiveness.model_dump(),
        price_change_limit_percent=Decimal(str(payload.price_change_limit_percent)),
        margin_policy=payload.margin_policy.model_dump(),
        step_up_percentage=Decimal(str(payload.step_up_percentage)),
        step_up_interval_hours=payload.step_up_interval_hours,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return _to_schema(profile, 0)


@router.get("/{profile_id}", response_model=RepricingProfileDetail)
async def get_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_db),
) -> RepricingProfileDetail:
    profile = await _get_profile(session, profile_id)
    return await _profile_detail(session, profile)


@router.put("/{profile_id}", response_model=RepricingProfileOut)
async def update_profile(
    profile_id: int,
    payload: RepricingProfileUpdate,
    session: AsyncSession = Depends(get_db),
) -> RepricingProfileOut:
    profile = await _get_profile(session, profile_id)
    if payload.name and payload.name != profile.name:
        duplicate = await session.scalar(
            select(RepricingProfile).where(
                RepricingProfile.name == payload.name, RepricingProfile.id != profile.id
            )
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Profile name already exists")
        profile.name = payload.name
    if payload.frequency_minutes is not None:
        profile.frequency_minutes = payload.frequency_minutes
    if payload.aggressiveness is not None:
        profile.aggressiveness = payload.aggressiveness.model_dump()
    if payload.price_change_limit_percent is not None:
        profile.price_change_limit_percent = Decimal(str(payload.price_change_limit_percent))
    if payload.margin_policy is not None:
        profile.margin_policy = payload.margin_policy.model_dump()
    if payload.step_up_percentage is not None:
        profile.step_up_percentage = Decimal(str(payload.step_up_percentage))
    if payload.step_up_interval_hours is not None:
        profile.step_up_interval_hours = payload.step_up_interval_hours
    await session.commit()
    await session.refresh(profile)
    sku_count = await session.scalar(select(func.count()).where(Sku.profile_id == profile.id))
    return _to_schema(profile, int(sku_count or 0))


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    profile = await _get_profile(session, profile_id)
    if profile.name == DEFAULT_PROFILE_NAME:
        raise HTTPException(status_code=400, detail="Default profile cannot be deleted")
    sku_count = await session.scalar(select(func.count()).where(Sku.profile_id == profile.id))
    if sku_count:
        raise HTTPException(status_code=400, detail="Profile has assigned SKUs")
    await session.delete(profile)
    await session.commit()
    return {"status": "deleted"}


@router.post("/{profile_id}/assign", response_model=RepricingProfileDetail)
async def assign_skus(
    profile_id: int,
    payload: ProfileAssignmentRequest,
    session: AsyncSession = Depends(get_db),
) -> RepricingProfileDetail:
    profile = await _get_profile(session, profile_id)
    if not payload.assignments:
        raise HTTPException(status_code=400, detail="No assignments provided")
    pairs = {(item.sku, item.marketplace_code) for item in payload.assignments}
    rows = (
        await session.execute(
            select(Sku.id, Sku.sku, Marketplace.code)
            .join(Marketplace)
            .where(tuple_(Sku.sku, Marketplace.code).in_(pairs))
        )
    ).all()
    found = {(sku, code): sku_id for sku_id, sku, code in rows}
    missing = [f"{sku}:{code}" for sku, code in pairs if (sku, code) not in found]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"SKUs not found: {', '.join(sorted(missing))}",
        )
    await session.execute(
        update(Sku).where(Sku.id.in_(found.values())).values(profile_id=profile.id)
    )
    await session.commit()
    await session.refresh(profile)
    return await _profile_detail(session, profile)
