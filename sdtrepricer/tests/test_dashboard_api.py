from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from sdtrepricer.app.api import api_router
from sdtrepricer.app.dependencies import get_db
from sdtrepricer.app.models import Alert, Marketplace, Sku, SystemSetting


@pytest.mark.anyio
async def test_dashboard_endpoint(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    sku = Sku(
        sku="SKU1",
        asin="ASIN1",
        marketplace=marketplace,
        min_price=Decimal("10"),
        min_business_price=Decimal("12"),
        hold_buy_box=True,
    )
    db_session.add_all(
        [
            marketplace,
            sku,
            Alert(message="Test alert", severity="WARNING"),
            SystemSetting(key="max_price_change_percent", value="15"),
            SystemSetting(key="step_up_type", value="absolute"),
            SystemSetting(key="step_up_value", value="1.5"),
            SystemSetting(key="step_up_interval_hours", value="4"),
        ]
    )
    await db_session.commit()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    class StubScheduler:
        def __init__(self) -> None:
            self.last_runs = {"DE": datetime.utcnow() - timedelta(minutes=5)}
            self.stats = {"DE": {"updated": 1, "processed": 10}}

    app.state.scheduler = StubScheduler()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/metrics/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"][0]["buy_box_skus"] == 1
    assert payload["alerts"][0]["message"] == "Test alert"
    assert payload["settings"]["step_up_type"] == "absolute"
    assert payload["settings"]["step_up_value"] == 1.5
    assert payload["settings"]["step_up_interval_hours"] == 4.0
