from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from sdtrepricer.app.models import Marketplace, PriceEvent, RepricingProfile, Sku
from sdtrepricer.app.services.ftp_loader import FloorPriceRecord
from sdtrepricer.app.services.repricer import PricingStrategy, Repricer


class StubFTP:
    def __init__(self, floor: FloorPriceRecord) -> None:
        self.floor = floor
        self.checked = False

    def validate_freshness(self, marketplace_code: str) -> bool:
        self.checked = True
        return True

    def load(self, marketplace_code: str):  # pragma: no cover - generator
        yield self.floor


class StubSPAPI:
    def __init__(self, competitor_price: float = 18.0) -> None:
        self.updates: list[tuple[str, float, float | None]] = []
        self.competitor_price = competitor_price

    async def get_competitive_pricing(self, marketplace_id: str, asins: list[str]):
        return {
            "data": [
                {
                    "asin": asins[0],
                    "offers": [
                        {
                            "sellerId": "A",
                            "isBuyBoxWinner": True,
                            "listingPrice": {"amount": 20.0},
                        },
                        {
                            "sellerId": "B",
                            "isBuyBoxWinner": False,
                            "listingPrice": {"amount": self.competitor_price},
                        },
                    ],
                }
            ]
        }

    async def submit_price_update(
        self, marketplace_id: str, sku: str, price: float, business_price: float | None
    ):
        self.updates.append((sku, price, business_price))
        return {"status": "OK"}

    async def close(self):  # pragma: no cover - compatibility
        return None


@pytest.mark.anyio
async def test_repricer_updates_prices(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    profile = RepricingProfile(
        name="Default",
        frequency_minutes=60,
        aggressiveness={"undercut_percent": 0.5},
        price_change_limit_percent=Decimal("20.0"),
        margin_policy={"min_margin_percent": 0.0},
        step_up_percentage=Decimal("2.0"),
        step_up_interval_hours=6,
    )
    sku = Sku(
        sku="SKU1",
        asin="ASIN1",
        marketplace=marketplace,
        profile=profile,
        min_price=Decimal("10.00"),
        min_business_price=Decimal("12.00"),
        last_updated_price=Decimal("15.00"),
    )
    db_session.add_all([marketplace, profile, sku])
    await db_session.commit()

    ftp = StubFTP(FloorPriceRecord("SKU1", "ASIN1", 10.0, 12.0))
    sp = StubSPAPI()
    repricer = Repricer(db_session, sp, ftp, PricingStrategy())

    result = await repricer.run_marketplace("DE")
    assert result["updated"] == 1
    assert ftp.checked
    await db_session.refresh(sku)
    assert float(sku.last_updated_price) > 15.0

    events = (await db_session.scalars(select(PriceEvent))).all()
    assert len(events) == 1
    assert events[0].reason == "repricer"
    assert sp.updates[0][0] == "SKU1"


@pytest.mark.anyio
async def test_profile_aggressiveness_applied(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    profile = RepricingProfile(
        name="Aggressive",
        frequency_minutes=15,
        aggressiveness={"undercut_percent": 5.0},
        price_change_limit_percent=Decimal("50.0"),
        margin_policy={"min_margin_percent": 0.0},
        step_up_percentage=Decimal("1.0"),
        step_up_interval_hours=6,
    )
    sku = Sku(
        sku="SKU2",
        asin="ASIN2",
        marketplace=marketplace,
        profile=profile,
        min_price=Decimal("10.00"),
        min_business_price=None,
        last_updated_price=Decimal("25.00"),
    )
    db_session.add_all([marketplace, profile, sku])
    await db_session.commit()

    ftp = StubFTP(FloorPriceRecord("SKU2", "ASIN2", 10.0, None))
    sp = StubSPAPI(competitor_price=20.0)
    repricer = Repricer(db_session, sp, ftp, PricingStrategy())

    result = await repricer.run_marketplace("DE", profile_id=profile.id)

    await db_session.refresh(sku)
    assert pytest.approx(float(sku.last_updated_price), rel=1e-3) == 19.0
    assert result["profile_id"] == profile.id
    assert profile.id in result.get("profiles_processed", [])
