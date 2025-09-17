from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from sdtrepricer.app.models import (
    Marketplace,
    PriceEvent,
    RepricingProfile,
    Sku,
    SystemSetting,
)
from sdtrepricer.app.services.ftp_loader import FloorPriceRecord
from sdtrepricer.app.services.repricer import PricingStrategy, Repricer
from sdtrepricer.app.services.test_data import ingest_competitor_data, ingest_floor_data


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


class RejectingFTP:
    def validate_freshness(self, marketplace_code: str) -> bool:  # pragma: no cover - safety
        raise AssertionError("FTP loader should not be used in test mode")

    def load(self, marketplace_code: str):  # pragma: no cover - safety
        raise AssertionError("FTP loader should not be used in test mode")


class RejectingSPAPI:
    async def get_competitive_pricing(self, marketplace_id: str, asins: list[str]):  # pragma: no cover
        raise AssertionError("Competitive pricing should not be fetched in test mode")

    async def submit_price_update(
        self, marketplace_id: str, sku: str, price: float, business_price: float | None
    ) -> None:  # pragma: no cover - safety
        raise AssertionError("Price updates should not be submitted in test mode")

    async def close(self):  # pragma: no cover - compatibility
        return None


@pytest.mark.anyio
async def test_repricer_updates_prices(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    profile = RepricingProfile(
        name="buy-box", step_up_type="absolute", step_up_value=Decimal("2.00"), step_up_interval_hours=1
    )
    sku = Sku(
        sku="SKU1",
        asin="ASIN1",
        marketplace=marketplace,
        min_price=Decimal("10.00"),
        min_business_price=Decimal("12.00"),
        last_updated_price=Decimal("15.00"),
        hold_buy_box=True,
        last_price_update=datetime.utcnow() - timedelta(hours=2),
        repricing_profile=profile,
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
    assert float(sku.last_updated_price) == 17.0

    events = (await db_session.scalars(select(PriceEvent))).all()
    assert len(events) == 1
    assert events[0].reason == "repricer"
    assert sp.updates[0][0] == "SKU1"


@pytest.mark.anyio
async def test_repricer_test_mode_uses_uploaded_data(db_session):
    marketplace = Marketplace(code="DE", name="Germany", amazon_id="A1")
    sku = Sku(
        sku="SKU1",
        asin="ASIN1",
        marketplace=marketplace,
        min_price=Decimal("10.00"),
        min_business_price=Decimal("12.00"),
        last_updated_price=Decimal("15.00"),
    )
    db_session.add_all(
        [
            marketplace,
            sku,
            SystemSetting(key="test_mode", value="true"),
        ]
    )
    await db_session.commit()

    floor_csv = "SKU,ASIN,MIN_PRICE,MIN_BUSINESS_PRICE\nSKU1,ASIN1,11.00,12.50\n"
    competitor_csv = "ASIN,SELLER_ID,PRICE,IS_BUY_BOX,FULFILLMENT_TYPE\nASIN1,S1,18.00,false,FBA\n"
    await ingest_floor_data(db_session, "DE", floor_csv.encode())
    await ingest_competitor_data(db_session, "DE", competitor_csv.encode())

    ftp = RejectingFTP()
    sp = RejectingSPAPI()
    repricer = Repricer(db_session, sp, ftp, PricingStrategy())

    result = await repricer.run_marketplace("DE")
    assert result["processed"] == 1
    assert result["updated"] == 1

    await db_session.refresh(sku)
    assert sku.last_updated_price == Decimal("15.00")

    events = (await db_session.scalars(select(PriceEvent))).all()
    assert len(events) == 1
    event = events[0]
    assert event.reason == "repricer-test"
    assert event.new_price is not None
    assert event.context["mode"] == "test"
    assert event.context["offers"][0]["seller_id"] == "S1"
