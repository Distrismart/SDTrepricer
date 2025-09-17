"""Core repricing logic."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.logging import logger
from ..models import AlertSeverity, Marketplace, PriceEvent, RepricingRun, Sku
from .alerts import create_alert
from .ftp_loader import FTPFeedLoader, FloorPriceRecord
from .sp_api import SPAPIClient


@dataclass
class CompetitorOffer:
    """Simplified competitor offer from SP-API response."""

    seller_id: str
    price: float
    is_buy_box: bool
    fulfillment_type: str


@dataclass
class PriceComputation:
    sku: Sku
    new_price: Decimal | None
    new_business_price: Decimal | None
    context: dict[str, Any]


class StepUpType(str, Enum):
    """Supported step-up configurations."""

    PERCENTAGE = "percentage"
    ABSOLUTE = "absolute"


@dataclass
class StepUpConfig:
    """Resolved step-up behaviour for a SKU evaluation."""

    type: StepUpType
    value: Decimal
    interval: timedelta


class PricingStrategy:
    """Encapsulate repricing rules."""

    def __init__(
        self,
        step_up_type: StepUpType | str | None = None,
        step_up_value: float | Decimal | None = None,
        step_up_interval_hours: float | None = None,
        max_daily_change_percent: float | None = None,
    ) -> None:
        self.step_up_type = self._normalize_step_up_type(step_up_type or settings.step_up_type)
        base_value = step_up_value if step_up_value is not None else settings.step_up_value
        self.step_up_value = base_value if isinstance(base_value, Decimal) else Decimal(str(base_value))
        interval_hours = float(
            step_up_interval_hours
            if step_up_interval_hours is not None
            else settings.step_up_interval_hours
        )
        self.step_up_interval_hours = interval_hours
        self.step_up_interval = timedelta(hours=interval_hours)
        self.max_daily_change_percent = (
            max_daily_change_percent
            if max_daily_change_percent is not None
            else settings.max_price_change_percent
        )

    def _normalize_step_up_type(self, value: StepUpType | str) -> StepUpType:
        if isinstance(value, StepUpType):
            return value
        try:
            return StepUpType(str(value).lower())
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported step-up type: {value}") from exc

    def _build_step_up_config(
        self,
        step_up_type: StepUpType | str | None,
        step_up_value: float | Decimal | None,
        step_up_interval_hours: float | None,
    ) -> StepUpConfig:
        resolved_type = self._normalize_step_up_type(step_up_type or self.step_up_type)
        base_value = step_up_value if step_up_value is not None else self.step_up_value
        decimal_value = base_value if isinstance(base_value, Decimal) else Decimal(str(base_value))
        interval_hours = float(
            step_up_interval_hours
            if step_up_interval_hours is not None
            else self.step_up_interval_hours
        )
        interval = timedelta(hours=interval_hours)
        return StepUpConfig(type=resolved_type, value=decimal_value, interval=interval)

    def _enforce_minimum(self, new_price: Decimal, sku: Sku) -> Decimal:
        return max(new_price, sku.min_price)

    def _enforce_daily_threshold(self, new_price: Decimal, sku: Sku) -> Decimal:
        if sku.last_updated_price is None:
            return new_price
        threshold = Decimal("1") + (Decimal(str(self.max_daily_change_percent)) / Decimal("100"))
        max_allowed = sku.last_updated_price * threshold
        min_allowed = sku.last_updated_price / threshold
        return min(max(new_price, min_allowed), max_allowed)

    def _step_up(self, sku: Sku, config: StepUpConfig) -> Decimal | None:
        if not sku.last_updated_price:
            return None
        if not sku.last_price_update:
            return None
        if datetime.utcnow() - sku.last_price_update < config.interval:
            return None
        if config.type is StepUpType.PERCENTAGE:
            multiplier = Decimal("1") + (config.value / Decimal("100"))
            return sku.last_updated_price * multiplier
        return sku.last_updated_price + config.value

    def determine_price(
        self,
        sku: Sku,
        offers: list[CompetitorOffer],
        floor: FloorPriceRecord,
        *,
        step_up_type: StepUpType | str | None = None,
        step_up_value: float | Decimal | None = None,
        step_up_interval_hours: float | None = None,
    ) -> PriceComputation:
        context: dict[str, Any] = {
            "competitor_count": len(offers),
            "hold_buy_box": sku.hold_buy_box,
        }
        step_up_config = self._build_step_up_config(
            step_up_type, step_up_value, step_up_interval_hours
        )
        context["step_up"] = {
            "type": step_up_config.type.value,
            "value": float(step_up_config.value),
            "interval_hours": step_up_config.interval.total_seconds() / 3600,
        }
        # Default to maintain last price if no offers
        candidate_price = sku.last_updated_price or Decimal(str(floor.min_price))
        if sku.hold_buy_box:
            step_up_price = self._step_up(sku, step_up_config)
            context["step_up_candidate"] = (
                float(step_up_price) if step_up_price is not None else None
            )
            if step_up_price is not None:
                candidate_price = max(candidate_price, step_up_price)
        else:
            # Find best competitor price
            competitor_prices = [offer.price for offer in offers if not offer.is_buy_box]
            if competitor_prices:
                best_competitor = min(competitor_prices)
                candidate_price = Decimal(str(best_competitor))
                context["target_competitor"] = best_competitor
                candidate_price *= Decimal("0.995")  # slight undercut by 0.5%
        candidate_price = max(candidate_price, Decimal(str(floor.min_price)))
        candidate_price = self._enforce_minimum(candidate_price, sku)
        candidate_price = self._enforce_daily_threshold(candidate_price, sku)
        business_price = (
            max(Decimal(str(floor.min_business_price)), candidate_price)
            if floor.min_business_price is not None
            else None
        )
        return PriceComputation(
            sku=sku,
            new_price=candidate_price,
            new_business_price=business_price,
            context=context,
        )


class Repricer:
    """Main repricing service handling orchestration."""

    def __init__(
        self,
        session: AsyncSession,
        sp_api: SPAPIClient,
        ftp_loader: FTPFeedLoader,
        strategy: PricingStrategy | None = None,
    ) -> None:
        self.session = session
        self.sp_api = sp_api
        self.ftp_loader = ftp_loader
        self.strategy = strategy or PricingStrategy()

    async def _fetch_skus(self, marketplace: Marketplace) -> list[Sku]:
        result = await self.session.execute(
            select(Sku)
            .options(selectinload(Sku.repricing_profile))
            .where(Sku.marketplace_id == marketplace.id)
        )
        return list(result.scalars().all())

    async def _fetch_offers(self, marketplace_id: str, asins: list[str]) -> dict[str, list[CompetitorOffer]]:
        offers: dict[str, list[CompetitorOffer]] = {asin: [] for asin in asins}
        response = await self.sp_api.get_competitive_pricing(marketplace_id, asins)
        for entry in response.get("data", []):
            asin = entry.get("asin") or entry.get("ASIN")
            offer_list = []
            for offer in entry.get("offers", []):
                price_info = offer.get("listingPrice", {})
                offer_list.append(
                    CompetitorOffer(
                        seller_id=offer.get("sellerId", "unknown"),
                        price=float(price_info.get("amount", 0.0)),
                        is_buy_box=offer.get("isBuyBoxWinner", False),
                        fulfillment_type=offer.get("fulfillmentType", "UNKNOWN"),
                    )
                )
            offers[asin] = offer_list
        return offers

    def _step_up_overrides(self, sku: Sku) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        profile = getattr(sku, "repricing_profile", None)
        if profile is not None:
            if isinstance(profile, dict):
                sources = [profile]
            else:
                sources = [
                    {
                        "step_up_type": getattr(profile, "step_up_type", None),
                        "step_up_value": getattr(profile, "step_up_value", None),
                        "step_up_interval_hours": getattr(profile, "step_up_interval_hours", None),
                    }
                ]
            for source in sources:
                for key in ("step_up_type", "step_up_value", "step_up_interval_hours"):
                    value = source.get(key)
                    if value is not None:
                        overrides[key] = value
        extra = getattr(sku, "profile_overrides", None)
        if isinstance(extra, dict):
            for key in ("step_up_type", "step_up_value", "step_up_interval_hours"):
                value = extra.get(key)
                if value is not None:
                    overrides[key] = value
        return overrides

    async def run_marketplace(self, marketplace_code: str) -> dict[str, Any]:
        run = RepricingRun(
            started_at=datetime.utcnow(),
            marketplace_id=0,
            status="running",
        )
        result = {
            "processed": 0,
            "updated": 0,
            "errors": 0,
            "marketplace": marketplace_code,
        }
        marketplace = await self.session.scalar(select(Marketplace).where(Marketplace.code == marketplace_code))
        if marketplace is None:
            logger.error("Marketplace %s not registered", marketplace_code)
            return result
        run.marketplace_id = marketplace.id
        self.session.add(run)
        await self.session.flush()
        skus = await self._fetch_skus(marketplace)
        if not skus:
            run.status = "empty"
            await self.session.commit()
            return result
        if not self.ftp_loader.validate_freshness(marketplace_code):
            await create_alert(
                self.session,
                f"FTP feed stale or missing for {marketplace_code}",
                AlertSeverity.WARNING,
            )
        try:
            floor_map = {record.sku: record for record in self.ftp_loader.load(marketplace_code)}
        except FileNotFoundError:
            await create_alert(
                self.session,
                f"FTP feed missing for {marketplace_code}",
                AlertSeverity.CRITICAL,
            )
            run.status = "blocked"
            await self.session.commit()
            return result
        batch_size = settings.repricing_batch_size
        concurrency = max(1, settings.repricing_concurrency)
        for window_start in range(0, len(skus), batch_size * concurrency):
            window = skus[window_start : window_start + batch_size * concurrency]
            tasks: list[tuple[list[Sku], asyncio.Task[dict[str, list[CompetitorOffer]]]]] = []
            for idx in range(0, len(window), batch_size):
                batch = window[idx : idx + batch_size]
                task = asyncio.create_task(
                    self._fetch_offers(marketplace.amazon_id, [sku.asin for sku in batch])
                )
                tasks.append((batch, task))
            for batch, task in tasks:
                offers = await task
                for sku in batch:
                    result["processed"] += 1
                    floor = floor_map.get(sku.sku)
                    if not floor:
                        logger.warning("Missing floor price for %s", sku.sku)
                        result["errors"] += 1
                        await create_alert(
                            self.session,
                            f"Missing floor price for SKU {sku.sku}",
                            AlertSeverity.WARNING,
                            {"marketplace": marketplace_code},
                        )
                        continue
                    overrides = self._step_up_overrides(sku)
                    computation = self.strategy.determine_price(
                        sku,
                        offers.get(sku.asin, []),
                        floor,
                        **overrides,
                    )
                    await self._apply_price(computation, marketplace)
                    if computation.new_price is not None:
                        result["updated"] += 1
        run.completed_at = datetime.utcnow()
        run.status = "completed"
        run.processed = result["processed"]
        run.updated = result["updated"]
        run.errors = result["errors"]
        await self.session.commit()
        logger.info("Completed repricing %s: %s", marketplace_code, result)
        return result

    async def _apply_price(self, computation: PriceComputation, marketplace: Marketplace) -> None:
        sku = computation.sku
        if computation.new_price is None:
            return
        if sku.last_updated_price == computation.new_price:
            return
        previous_price = sku.last_updated_price
        previous_business_price = sku.last_updated_business_price
        payload = await self.sp_api.submit_price_update(
            marketplace.amazon_id,
            sku.sku,
            float(computation.new_price),
            float(computation.new_business_price) if computation.new_business_price else None,
        )
        sku.last_updated_price = computation.new_price
        sku.last_updated_business_price = computation.new_business_price
        sku.last_price_update = datetime.utcnow()
        event = PriceEvent(
            sku_id=sku.id,
            created_at=datetime.utcnow(),
            old_price=previous_price,
            new_price=computation.new_price,
            old_business_price=previous_business_price,
            new_business_price=computation.new_business_price,
            reason="repricer",
            context={"api": payload} | computation.context,
        )
        self.session.add(event)
