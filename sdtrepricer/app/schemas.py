"""Pydantic schemas for API responses and requests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class MarketplaceMetrics(BaseModel):
    """Metrics for a marketplace."""

    code: str
    name: str
    buy_box_skus: int
    total_skus: int
    buy_box_percentage: float = Field(..., description="Current buy box win percentage")


class SystemHealth(BaseModel):
    """Health check payload."""

    status: str
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class AlertPayload(BaseModel):
    """Alert details for UI."""

    id: int
    message: str
    severity: str
    created_at: datetime
    acknowledged: bool
    metadata: dict[str, Any] | None = None


class RepricerSettings(BaseModel):
    """Repricer configurable options."""

    max_price_change_percent: float
    step_up_percentage: float
    step_up_interval_hours: int
    test_mode: bool


class SimulatedPriceOutcome(BaseModel):
    """Preview of a simulated price change while in test mode."""

    sku: str
    marketplace_code: str
    created_at: datetime
    old_price: Decimal | None
    new_price: Decimal | None
    old_business_price: Decimal | None = None
    new_business_price: Decimal | None = None
    context: dict[str, Any] | None = None


class ManualRepriceRequest(BaseModel):
    """Payload to trigger manual repricing of SKUs."""

    marketplace_code: str
    skus: list[str]


class ManualPriceUpdate(BaseModel):
    """Manual price update via UI."""

    marketplace_code: str
    sku: str
    price: Decimal
    business_price: Decimal | None = None


class BulkFeedUploadResponse(BaseModel):
    """Response for manual feed upload."""

    feed_id: str
    submitted_at: datetime
    status: str


class DashboardPayload(BaseModel):
    """Combined payload for the dashboard."""

    metrics: list[MarketplaceMetrics]
    health: SystemHealth
    alerts: list[AlertPayload]
    settings: RepricerSettings
    simulated_events: list[SimulatedPriceOutcome] = Field(default_factory=list)
