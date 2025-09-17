"""Scheduler handling repricing triggers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..core.config import settings
from ..core.database import get_session
from ..core.logging import logger
from ..models import Marketplace, RepricingProfile, Sku
from .ftp_loader import FTPFeedLoader
from .repricer import Repricer
from .sp_api import create_sp_api_client


class RepricingScheduler:
    """Coordinate event-driven repricing and scheduled fallbacks."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.last_runs: dict[str, datetime] = {}
        self.stats: dict[str, dict[str, Any]] = defaultdict(dict)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Scheduler started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            logger.info("Scheduler stopped")

    def _key(self, marketplace_code: str, profile_id: int | None) -> str:
        suffix = str(profile_id) if profile_id is not None else "all"
        return f"{marketplace_code}:{suffix}"

    async def trigger_marketplace(
        self, marketplace_code: str, reason: str = "manual", profile_id: int | None = None
    ) -> None:
        await self.queue.put(
            (
                "repricer",
                {"marketplace_code": marketplace_code, "reason": reason, "profile_id": profile_id},
            )
        )

    async def handle_notification(self, payload: dict[str, Any]) -> None:
        marketplace_code = payload.get("marketplace_code")
        if marketplace_code:
            await self.trigger_marketplace(marketplace_code, reason="notification")

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item_type, data = await asyncio.wait_for(
                    self.queue.get(), timeout=settings.scheduler_tick_seconds
                )
                if item_type == "repricer":
                    await self._handle_reprice_request(data)
            except asyncio.TimeoutError:
                await self._run_scheduled_cycle()
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Scheduler loop error: %s", exc)

    async def _handle_reprice_request(self, data: dict[str, Any]) -> None:
        marketplace_code = data["marketplace_code"]
        profile_id = data.get("profile_id")
        logger.info(
            "Trigger repricing for %s (profile=%s) due to %s",
            marketplace_code,
            profile_id,
            data.get("reason"),
        )
        async with get_session() as session:
            sp_api_client = await create_sp_api_client()
            try:
                ftp_loader = FTPFeedLoader()
                repricer = Repricer(session, sp_api_client, ftp_loader)
                result = await repricer.run_marketplace(marketplace_code, profile_id=profile_id)
                key = self._key(marketplace_code, profile_id)
                self.stats[key] = result
                now = datetime.utcnow()
                processed_profiles = set(result.get("profiles_processed", []))
                if profile_id is not None:
                    processed_profiles.add(profile_id)
                for processed in processed_profiles:
                    self.last_runs[self._key(marketplace_code, processed)] = now
                self.last_runs[key] = now
            finally:
                await sp_api_client.close()

    async def _run_scheduled_cycle(self) -> None:
        async with get_session() as session:
            marketplaces = (await session.scalars(select(Marketplace))).all()
            profile_rows = (
                await session.execute(
                    select(
                        Marketplace.code,
                        RepricingProfile.id,
                        RepricingProfile.frequency_minutes,
                    )
                    .join(Sku, Sku.marketplace_id == Marketplace.id)
                    .join(RepricingProfile, Sku.profile_id == RepricingProfile.id)
                    .distinct()
                )
            ).all()
        profiles_by_marketplace: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for code, profile_id, frequency in profile_rows:
            profiles_by_marketplace[code].append((profile_id, frequency))
        for marketplace in marketplaces:
            profiles = profiles_by_marketplace.get(marketplace.code)
            if not profiles:
                key = self._key(marketplace.code, None)
                last_run = self.last_runs.get(key)
                if last_run and (
                    datetime.utcnow() - last_run
                ).total_seconds() < settings.scheduler_tick_seconds:
                    continue
                await self.trigger_marketplace(marketplace.code, reason="scheduled")
                continue
            for profile_id, frequency in profiles:
                key = self._key(marketplace.code, profile_id)
                last_run = self.last_runs.get(key)
                interval = timedelta(minutes=frequency)
                if last_run and datetime.utcnow() - last_run < interval:
                    continue
                await self.trigger_marketplace(
                    marketplace.code, reason="scheduled", profile_id=profile_id
                )
