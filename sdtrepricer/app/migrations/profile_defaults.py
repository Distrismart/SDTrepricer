"""Utilities to create the default repricing profile."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RepricingProfile, Sku

DEFAULT_PROFILE_NAME = "Default"


def _profile_defaults() -> dict[str, object]:
    return {
        "undercut_percent": 0.5,
    }


def _margin_defaults() -> dict[str, object]:
    return {
        "min_margin_percent": 0.0,
    }


async def ensure_default_profile_assignment(session: AsyncSession) -> None:
    """Create a default profile and backfill SKUs lacking assignment."""

    profile = await session.scalar(
        select(RepricingProfile).where(RepricingProfile.name == DEFAULT_PROFILE_NAME)
    )
    if profile is None:
        profile = RepricingProfile(
            name=DEFAULT_PROFILE_NAME,
            frequency_minutes=60,
            aggressiveness=_profile_defaults(),
            price_change_limit_percent=Decimal("20.00"),
            margin_policy=_margin_defaults(),
            step_up_percentage=Decimal("2.00"),
            step_up_interval_hours=6,
        )
        session.add(profile)
        await session.flush()
    await session.execute(
        update(Sku).where(Sku.profile_id.is_(None)).values(profile_id=profile.id)
    )
    await session.commit()
