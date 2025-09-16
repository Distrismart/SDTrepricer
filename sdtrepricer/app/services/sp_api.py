"""Amazon SP-API integration helpers."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import settings
from ..core.logging import logger


class RateLimitError(Exception):
    """Raised when API throttle occurs."""


@dataclass
class RateQuota:
    """Track Amazon SP-API rate quotas."""

    rate: float
    burst: int
    restore_rate: float


class TokenRefresher:
    """Handle refreshing LWA tokens."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            now = time.monotonic()
            if self._token and now < self._expires_at - 60:
                return self._token
            # Placeholder token refresh logic - integrate with LWA in production
            self._token = "mock-token"
            self._expires_at = now + 3600
            logger.debug("Refreshed LWA token")
            return self._token


class SPAPIClient:
    """Minimal SP-API client with retry and quota tracking."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._token_refresher = TokenRefresher()
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._request_log: deque[float] = deque(maxlen=1000)
        self._quota = RateQuota(rate=0.1, burst=1, restore_rate=0.1)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._request_log and len(self._request_log) >= self._quota.burst:
                oldest = self._request_log[0]
                delay = max(0.0, (1 / self._quota.rate) - (now - oldest))
                if delay > 0:
                    logger.debug("Throttling for %s seconds", delay)
                    await asyncio.sleep(delay)
            self._request_log.append(now)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await self._token_refresher.get_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("x-amz-access-token", token)
        kwargs["headers"] = headers

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=60),
            retry=retry_if_exception_type((httpx.RequestError, RateLimitError)),
            reraise=True,
        ):
            with attempt:
                await self._throttle()
                response = await self._client.request(method, url, **kwargs)
                if response.status_code == 429:
                    raise RateLimitError("API throttled")
                response.raise_for_status()
                return response
        raise RuntimeError("Unreachable")

    async def get_competitive_pricing(self, marketplace_id: str, asins: list[str]) -> dict[str, Any]:
        """Fetch competitive pricing data for a list of ASINs."""

        endpoint = f"{settings.sp_api_endpoint}/products/pricing/v0/competitivePrice"
        params = {"MarketplaceId": marketplace_id, "Asins": ",".join(asins)}
        try:
            response = await self._request("GET", endpoint, params=params)
        except RetryError as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to fetch pricing for %s: %s", asins, exc)
            raise
        # In test environment we emulate expected structure
        payload = response.json() if response.content else {"data": []}
        return payload

    async def submit_price_update(
        self,
        marketplace_id: str,
        sku: str,
        price: float,
        business_price: float | None,
    ) -> dict[str, Any]:
        """Submit price update to Listings API."""

        endpoint = f"{settings.sp_api_endpoint}/listings/2021-08-01/items/{settings.sp_api_client_id or 'seller'}/{sku}/price"
        body = {
            "MarketplaceId": marketplace_id,
            "PriceType": "B2B" if business_price else "B2C",
            "StandardPrice": price,
        }
        if business_price is not None:
            body["BusinessPrice"] = business_price
        response = await self._request("PATCH", endpoint, json=body)
        return response.json() if response.content else {"status": "submitted"}

    async def submit_bulk_feed(self, document: bytes, content_type: str) -> dict[str, Any]:
        """Upload a bulk pricing feed."""

        endpoint = f"{settings.sp_api_endpoint}/feeds/2021-06-30/documents"
        files = {"file": ("bulk.xml", document, content_type)}
        response = await self._request("POST", endpoint, files=files)
        return response.json() if response.content else {"feedDocumentId": "mock"}

    async def acknowledge_notification(self, notification_id: str) -> None:
        """Acknowledge SP-API notification."""

        endpoint = f"{settings.sp_api_endpoint}/notifications/v1/acknowledgements/{notification_id}"
        await self._request("POST", endpoint)


async def create_sp_api_client() -> SPAPIClient:
    """Factory for dependency injection."""

    return SPAPIClient()
