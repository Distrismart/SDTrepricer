from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sdtrepricer.app.api import api_router
from sdtrepricer.app.dependencies import get_db
from sdtrepricer.app.models import Marketplace, Sku


@pytest.mark.anyio
async def test_profile_crud_and_assignment(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    sku = Sku(
        sku="SKU-PROFILE",
        asin="ASIN-PROFILE",
        marketplace=marketplace,
        profile=None,
        min_price=Decimal("9.99"),
        min_business_price=None,
    )
    db_session.add_all([marketplace, sku])
    await db_session.commit()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_payload = {
            "name": "Evening",
            "frequency_minutes": 45,
            "aggressiveness": {"undercut_percent": 1.5},
            "price_change_limit_percent": 25.0,
            "margin_policy": {"min_margin_percent": 2.0},
            "step_up_percentage": 3.0,
            "step_up_interval_hours": 4,
        }
        response = await client.post("/api/profiles/", json=create_payload)
        assert response.status_code == 201
        profile = response.json()
        profile_id = profile["id"]

        assign_payload = {
            "assignments": [
                {"sku": "SKU-PROFILE", "marketplace_code": "DE"},
            ]
        }
        response = await client.post(f"/api/profiles/{profile_id}/assign", json=assign_payload)
        assert response.status_code == 200
        detail = response.json()
        assert detail["sku_count"] == 1
        assert detail["skus"][0]["sku"] == "SKU-PROFILE"

        response = await client.get(f"/api/profiles/{profile_id}")
        assert response.status_code == 200
        assert response.json()["sku_count"] == 1

        response = await client.put(
            f"/api/profiles/{profile_id}",
            json={"frequency_minutes": 30, "name": "Evening Update"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["frequency_minutes"] == 30
        assert payload["name"] == "Evening Update"

        response = await client.get("/api/profiles/")
        assert response.status_code == 200
        profiles = response.json()
        assert any(item["sku_count"] == 1 for item in profiles if item["id"] == profile_id)
