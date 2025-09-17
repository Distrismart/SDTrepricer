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


class ManualRepriceRequest(BaseModel):
    """Payload to trigger manual repricing of SKUs."""

    marketplace_code: str
    skus: list[str]
    profile_id: int | None = None


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


class AggressivenessSettings(BaseModel):
    """Controls around undercutting and competitiveness."""

    undercut_percent: float = Field(0.5, ge=0, le=100)


class MarginPolicy(BaseModel):
    """Margin guardrails applied per profile."""

    min_margin_percent: float = Field(0.0, ge=0)


class RepricingProfileBase(BaseModel):
    """Shared fields for profile definitions."""

    frequency_minutes: int = Field(60, ge=5, description="Run cadence in minutes")
    aggressiveness: AggressivenessSettings = Field(default_factory=AggressivenessSettings)
    price_change_limit_percent: float = Field(20.0, gt=0)
    margin_policy: MarginPolicy = Field(default_factory=MarginPolicy)
    step_up_percentage: float = Field(2.0, ge=0)
    step_up_interval_hours: int = Field(6, ge=1)


class RepricingProfileCreate(RepricingProfileBase):
    """Create payload for repricing profiles."""

    name: str


class RepricingProfileUpdate(BaseModel):
    """Mutable fields for repricing profiles."""

    name: str | None = None
    frequency_minutes: int | None = Field(None, ge=5)
    aggressiveness: AggressivenessSettings | None = None
    price_change_limit_percent: float | None = Field(None, gt=0)
    margin_policy: MarginPolicy | None = None
    step_up_percentage: float | None = Field(None, ge=0)
    step_up_interval_hours: int | None = Field(None, ge=1)


class RepricingProfileOut(RepricingProfileBase):
    """Profile details returned from the API."""

    id: int
    name: str
    sku_count: int = 0
    created_at: datetime


class RepricingProfileDetail(RepricingProfileOut):
    """Detailed view including assigned SKUs."""

    skus: list[ProfileSkuSummary] = Field(default_factory=list)


class ProfileSkuSummary(BaseModel):
    """Summary of SKUs assigned to a profile."""

    id: int
    sku: str
    asin: str
    marketplace_code: str


class ProfileAssignment(BaseModel):
    """Descriptor for assigning a SKU to a profile."""

    sku: str
    marketplace_code: str


class ProfileAssignmentRequest(BaseModel):
    """Payload to assign SKUs to a repricing profile."""

    assignments: list[ProfileAssignment]
