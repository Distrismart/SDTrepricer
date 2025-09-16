from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from sdtrepricer.app.models import Marketplace, PriceEvent, Sku
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
    def __init__(self) -> None:
        self.updates: list[tuple[str, float, float | None]] = []

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
                            "listingPrice": {"amount": 18.0},
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
    sku = Sku(
        sku="SKU1",
        asin="ASIN1",
        marketplace=marketplace,
        min_price=Decimal("10.00"),
        min_business_price=Decimal("12.00"),
        last_updated_price=Decimal("15.00"),
    )
    db_session.add(marketplace)
    db_session.add(sku)
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
