"""Core repricing logic."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.logging import logger

from ..models import AlertSeverity, Marketplace, PriceEvent, RepricingProfile, RepricingRun, Sku

from .alerts import create_alert
from .ftp_loader import FTPFeedLoader, FloorPriceRecord
from .sp_api import SPAPIClient
from .test_data import load_competitor_offers, load_floor_prices


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
        undercut_percent: float = 0.5,
        min_margin_percent: float = 0.0,
    ) -> None:

        self.step_up_percentage = step_up_percentage
        self.step_up_interval = timedelta(hours=step_up_interval_hours)

        self.max_daily_change_percent = (
            max_daily_change_percent
            if max_daily_change_percent is not None
            else settings.max_price_change_percent
        )

        self.undercut_percent = undercut_percent
        self.min_margin_percent = min_margin_percent


    def _enforce_minimum(self, new_price: Decimal, sku: Sku) -> Decimal:
        return max(new_price, sku.min_price)

    def _enforce_daily_threshold(self, new_price: Decimal, sku: Sku) -> Decimal:
        if sku.last_updated_price is None:
            return new_price
        threshold = Decimal("1") + (Decimal(str(self.max_daily_change_percent)) / Decimal("100"))
        max_allowed = sku.last_updated_price * threshold
        min_allowed = sku.last_updated_price / threshold
        return min(max(new_price, min_allowed), max_allowed)


    def _apply_margin_policy(self, new_price: Decimal, floor: FloorPriceRecord) -> Decimal:
        if self.min_margin_percent <= 0:
            return new_price
        baseline = Decimal(str(floor.min_price))
        margin_ratio = Decimal("1") + Decimal(str(self.min_margin_percent)) / Decimal("100")
        required = baseline * margin_ratio
        return max(new_price, required)

    def _step_up(self, sku: Sku) -> Decimal | None:

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
            "undercut_percent": self.undercut_percent,
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
                undercut_ratio = Decimal(str(self.undercut_percent)) / Decimal("100")
                undercut_ratio = max(Decimal("0"), min(undercut_ratio, Decimal("1")))
                candidate_price *= Decimal("1") - undercut_ratio
        candidate_price = max(candidate_price, Decimal(str(floor.min_price)))
        candidate_price = self._apply_margin_policy(candidate_price, floor)
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
        test_mode: bool | None = None,
    ) -> None:
        self.session = session
        self.sp_api = sp_api
        self.ftp_loader = ftp_loader
        self.strategy = strategy or PricingStrategy()
        self._test_mode_override = test_mode

    async def _is_test_mode(self) -> bool:
        if self._test_mode_override is not None:
            return self._test_mode_override
        setting = await self.session.scalar(
            select(SystemSetting).where(SystemSetting.key == "test_mode")
        )
        if setting:
            return setting.value.lower() in {"1", "true", "yes", "on"}
        return settings.test_mode


    async def _fetch_skus(
        self, marketplace: Marketplace, profile_id: int | None = None
    ) -> list[Sku]:
        stmt = (
            select(Sku)
            .where(Sku.marketplace_id == marketplace.id)
            .options(selectinload(Sku.profile))
        )
        if profile_id is not None:
            stmt = stmt.where(Sku.profile_id == profile_id)
        result = await self.session.execute(stmt)

        return list(result.scalars().all())

    def _strategy_for_profile(self, profile: RepricingProfile | None) -> PricingStrategy:
        if profile is None:
            return self.strategy
        aggressiveness = profile.aggressiveness or {}
        margin_policy = profile.margin_policy or {}
        undercut = float(aggressiveness.get("undercut_percent", self.strategy.undercut_percent))
        min_margin = float(margin_policy.get("min_margin_percent", self.strategy.min_margin_percent))
        return PricingStrategy(
            step_up_percentage=float(profile.step_up_percentage or 0),
            step_up_interval_hours=profile.step_up_interval_hours,
            max_daily_change_percent=float(profile.price_change_limit_percent or 0),
            undercut_percent=undercut,
            min_margin_percent=min_margin,
        )

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


    async def run_marketplace(
        self, marketplace_code: str, profile_id: int | None = None
    ) -> dict[str, Any]:

        run = RepricingRun(
            started_at=datetime.utcnow(),
            marketplace_id=0,
            status="test-running" if test_mode else "running",
        )
        result = {
            "processed": 0,
            "updated": 0,
            "errors": 0,
            "marketplace": marketplace_code,
            "profile_id": profile_id,
        }
        marketplace = await self.session.scalar(select(Marketplace).where(Marketplace.code == marketplace_code))
        if marketplace is None:
            logger.error("Marketplace %s not registered", marketplace_code)
            return result
        run.marketplace_id = marketplace.id
        self.session.add(run)
        await self.session.flush()
        skus = await self._fetch_skus(marketplace, profile_id=profile_id)
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
        strategy_cache: dict[int | None, PricingStrategy] = {None: self.strategy}
        processed_profiles: set[int] = set()
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
                    profile_key = sku.profile_id
                    strategy = strategy_cache.get(profile_key)
                    if strategy is None:
                        strategy = self._strategy_for_profile(sku.profile)
                        strategy_cache[profile_key] = strategy
                    computation = strategy.determine_price(sku, offers.get(sku.asin, []), floor)
                    await self._apply_price(computation, marketplace)
                    if computation.new_price is not None:
                        result["updated"] += 1
                    if profile_key is not None:
                        processed_profiles.add(profile_key)

        run.completed_at = datetime.utcnow()
        run.status = "test-completed" if test_mode else "completed"
        run.processed = result["processed"]
        run.updated = result["updated"]
        run.errors = result["errors"]
        await self.session.commit()
        if processed_profiles:
            result["profiles_processed"] = sorted(processed_profiles)
        logger.info("Completed repricing %s: %s", marketplace_code, result)
        return result

    async def _apply_price(
        self,
        computation: PriceComputation,
        marketplace: Marketplace,
        test_mode: bool,
        offers: list[CompetitorOffer],
    ) -> None:
        sku = computation.sku
        if computation.new_price is None:
            return
        if not test_mode and sku.last_updated_price == computation.new_price:
            return
        previous_price = sku.last_updated_price
        previous_business_price = sku.last_updated_business_price
        if test_mode:
            event = PriceEvent(
                sku_id=sku.id,
                created_at=datetime.utcnow(),
                old_price=previous_price,
                new_price=computation.new_price,
                old_business_price=previous_business_price,
                new_business_price=computation.new_business_price,
                reason="repricer-test",
                context={
                    "mode": "test",
                    "offers": [asdict(offer) for offer in offers],
                    "computation": computation.context,
                },
            )
            self.session.add(event)
            return
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
