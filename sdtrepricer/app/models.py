"""Database models for the repricer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class."""


class Marketplace(Base):
    """Amazon marketplace definition."""

    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    amazon_id: Mapped[str] = mapped_column(String(32), nullable=False)

    skus: Mapped[list["Sku"]] = relationship(
        "Sku", back_populates="marketplace", cascade="all, delete-orphan"
    )


class RepricingProfile(Base):
    """Reusable repricing strategy configuration."""


    __tablename__ = "repricing_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    frequency_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    aggressiveness: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    price_change_limit_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    margin_policy: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    step_up_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2.00"))
    step_up_interval_hours: Mapped[int] = mapped_column(Integer, default=6)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    skus: Mapped[list["Sku"]] = relationship("Sku", back_populates="profile")



class Sku(Base):
    """SKU level configuration and metrics."""

    __tablename__ = "skus"
    __table_args__ = (UniqueConstraint("sku", "marketplace_id", name="uq_sku_marketplace"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplaces.id", ondelete="CASCADE"))
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("repricing_profiles.id", ondelete="SET NULL"), nullable=True
    )
    min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_business_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    last_min_price_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_buy_box: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    last_updated_business_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    last_price_update: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_buy_box_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repricing_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("repricing_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    marketplace: Mapped["Marketplace"] = relationship("Marketplace", back_populates="skus")

    profile: Mapped[RepricingProfile | None] = relationship("RepricingProfile", back_populates="skus")

    price_events: Mapped[list["PriceEvent"]] = relationship(
        "PriceEvent", back_populates="sku", cascade="all, delete-orphan"
    )


class RepricingRun(Base):
    """Repricing batch run telemetry."""

    __tablename__ = "repricing_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplaces.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)

    marketplace: Mapped["Marketplace"] = relationship("Marketplace")


class PriceEvent(Base):
    """Historical price changes for auditing and reporting."""

    __tablename__ = "price_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    old_business_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    new_business_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    context: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    sku: Mapped["Sku"] = relationship("Sku", back_populates="price_events")


class AlertSeverity(str, PyEnum):
    """Severity levels for alerts."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Alert(Base):
    """System alert for monitoring."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default=AlertSeverity.INFO.value)
    metadata_payload: Mapped[dict[str, object] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class TestFloorPrice(Base):
    """Uploaded floor price data used while running in test mode."""

    __tablename__ = "test_floor_prices"
    __table_args__ = (UniqueConstraint("marketplace_code", "sku", name="uq_test_floor_marketplace_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace_code: Mapped[str] = mapped_column(String(4), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_business_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class TestCompetitorOffer(Base):
    """Uploaded competitor offers used while running in test mode."""

    __tablename__ = "test_competitor_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace_code: Mapped[str] = mapped_column(String(4), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    seller_id: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_buy_box: Mapped[bool] = mapped_column(Boolean, default=False)
    fulfillment_type: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")


class SystemSetting(Base):
    """Mutable system wide settings exposed via the UI."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
