from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sdtrepricer.app.models import Sku
from sdtrepricer.app.services.ftp_loader import FloorPriceRecord
from sdtrepricer.app.services.repricer import CompetitorOffer, PricingStrategy


def build_sku(**kwargs):
    defaults = {
        "sku": "SKU123",
        "asin": "ASIN123",
        "marketplace_id": 1,
        "min_price": Decimal("10.00"),
        "min_business_price": Decimal("12.00"),
    }
    defaults.update(kwargs)
    return Sku(**defaults)


def test_competitor_undercut():
    sku = build_sku(last_updated_price=Decimal("15.00"))
    floor = FloorPriceRecord("SKU123", "ASIN123", 10.0, 12.0)
    offers = [
        CompetitorOffer("sellerA", 14.50, False, "FBA"),
        CompetitorOffer("sellerB", 16.00, True, "FBM"),
    ]
    strategy = PricingStrategy()
    result = strategy.determine_price(sku, offers, floor)
    assert result.new_price < Decimal("15.00")
    assert result.new_price >= Decimal("10.00")


def test_buy_box_percentage_step_up():
    sku = build_sku(
        hold_buy_box=True,
        last_updated_price=Decimal("20.00"),
        last_price_update=datetime.utcnow() - timedelta(hours=8),
    )
    floor = FloorPriceRecord("SKU123", "ASIN123", 10.0, 12.0)
    strategy = PricingStrategy(
        step_up_type="percentage",
        step_up_value=5,
        step_up_interval_hours=6,
        max_daily_change_percent=100,
    )
    result = strategy.determine_price(sku, [], floor)
    assert result.new_price >= Decimal("21.00")
    assert result.context["step_up"]["type"] == "percentage"


def test_buy_box_absolute_step_up():
    sku = build_sku(
        hold_buy_box=True,
        last_updated_price=Decimal("20.00"),
        last_price_update=datetime.utcnow() - timedelta(hours=8),
    )
    floor = FloorPriceRecord("SKU123", "ASIN123", 10.0, 12.0)
    strategy = PricingStrategy(
        step_up_type="absolute",
        step_up_value=Decimal("2.50"),
        step_up_interval_hours=4,
        max_daily_change_percent=100,
    )
    result = strategy.determine_price(sku, [], floor)
    assert result.new_price == Decimal("22.50")
    assert result.context["step_up"]["type"] == "absolute"


def test_step_up_interval_enforced():
    sku = build_sku(
        hold_buy_box=True,
        last_updated_price=Decimal("20.00"),
        last_price_update=datetime.utcnow() - timedelta(hours=1),
    )
    floor = FloorPriceRecord("SKU123", "ASIN123", 10.0, 12.0)
    strategy = PricingStrategy(
        step_up_type="absolute",
        step_up_value=Decimal("5.00"),
        step_up_interval_hours=6,
        max_daily_change_percent=100,
    )
    result = strategy.determine_price(sku, [], floor)
    assert result.new_price == Decimal("20.00")
    assert result.context["step_up_candidate"] is None


def test_daily_threshold_is_enforced():
    sku = build_sku(last_updated_price=Decimal("20.00"))
    floor = FloorPriceRecord("SKU123", "ASIN123", 10.0, 12.0)
    offers = [CompetitorOffer("sellerA", 40.0, False, "FBA")]
    strategy = PricingStrategy(max_daily_change_percent=10)
    result = strategy.determine_price(sku, offers, floor)
    assert result.new_price <= Decimal("22.00")
