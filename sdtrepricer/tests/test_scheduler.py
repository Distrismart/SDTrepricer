from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from sdtrepricer.app.models import Marketplace, RepricingProfile, Sku
from sdtrepricer.app.services.scheduler import RepricingScheduler


@pytest.mark.anyio
async def test_scheduler_uses_profile_frequency(db_session, monkeypatch):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    fast_profile = RepricingProfile(
        name="Fast",
        frequency_minutes=15,
        aggressiveness={"undercut_percent": 1.0},
        price_change_limit_percent=Decimal("40.0"),
        margin_policy={"min_margin_percent": 0.0},
        step_up_percentage=Decimal("2.0"),
        step_up_interval_hours=6,
    )
    slow_profile = RepricingProfile(
        name="Slow",
        frequency_minutes=120,
        aggressiveness={"undercut_percent": 0.5},
        price_change_limit_percent=Decimal("40.0"),
        margin_policy={"min_margin_percent": 0.0},
        step_up_percentage=Decimal("2.0"),
        step_up_interval_hours=6,
    )
    sku_fast = Sku(
        sku="FAST-SKU",
        asin="FAST",
        marketplace=marketplace,
        profile=fast_profile,
        min_price=Decimal("10.00"),
        min_business_price=None,
    )
    sku_slow = Sku(
        sku="SLOW-SKU",
        asin="SLOW",
        marketplace=marketplace,
        profile=slow_profile,
        min_price=Decimal("10.00"),
        min_business_price=None,
    )
    db_session.add_all([marketplace, fast_profile, slow_profile, sku_fast, sku_slow])
    await db_session.commit()

    scheduler = RepricingScheduler()
    calls: list[tuple[str, int | None]] = []

    async def fake_trigger(marketplace_code: str, reason: str = "manual", profile_id: int | None = None):
        calls.append((marketplace_code, profile_id))

    scheduler.trigger_marketplace = fake_trigger  # type: ignore[assignment]

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr("sdtrepricer.app.services.scheduler.get_session", fake_session)

    await scheduler._run_scheduled_cycle()
    assert (marketplace.code, fast_profile.id) in calls
    assert (marketplace.code, slow_profile.id) in calls

    calls.clear()
    scheduler.last_runs[scheduler._key(marketplace.code, fast_profile.id)] = datetime.utcnow()
    scheduler.last_runs[scheduler._key(marketplace.code, slow_profile.id)] = datetime.utcnow() - timedelta(
        minutes=slow_profile.frequency_minutes + 1
    )

    await scheduler._run_scheduled_cycle()
    assert calls == [(marketplace.code, slow_profile.id)]
