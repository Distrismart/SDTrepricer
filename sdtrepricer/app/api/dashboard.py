"""Dashboard endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..dependencies import get_db
from ..models import Alert, Marketplace, Sku, SystemSetting
from ..schemas import AlertPayload, DashboardPayload, MarketplaceMetrics, RepricerSettings, SystemHealth

router = APIRouter()


@router.get("/dashboard", response_model=DashboardPayload)
async def get_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> DashboardPayload:
    marketplaces = (await session.scalars(select(Marketplace))).all()
    sku_stats = await session.execute(
        select(
            Sku.marketplace_id,
            func.count(Sku.id).label("total"),
            func.coalesce(
                func.sum(case((Sku.hold_buy_box.is_(True), 1), else_=0)),
                0,
            ).label("buy_box"),
        ).group_by(Sku.marketplace_id)
    )
    stats_map = {row.marketplace_id: row for row in sku_stats}
    metrics: list[MarketplaceMetrics] = []
    for marketplace in marketplaces:
        stat = stats_map.get(marketplace.id)
        total = stat.total if stat else 0
        buy_box = stat.buy_box if stat else 0
        percentage = float(buy_box) / total * 100 if total else 0.0
        metrics.append(
            MarketplaceMetrics(
                code=marketplace.code,
                name=marketplace.name,
                buy_box_skus=int(buy_box),
                total_skus=int(total),
                buy_box_percentage=percentage,
            )
        )
    alerts_rows = (
        await session.execute(
            select(Alert).order_by(Alert.created_at.desc()).limit(20)
        )
    ).scalars()
    alerts = [
        AlertPayload(
            id=alert.id,
            message=alert.message,
            severity=alert.severity,
            created_at=alert.created_at,
            acknowledged=alert.acknowledged,
            metadata=alert.metadata_payload,
        )
        for alert in alerts_rows
    ]
    settings_rows = (
        await session.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_(
                    {
                        "max_price_change_percent",
                        "step_up_type",
                        "step_up_value",
                        "step_up_interval_hours",
                        "step_up_percentage",
                    }
                )
            )
        )
    ).scalars().all()
    settings_map = {row.key: row.value for row in settings_rows}
    repricer_settings = RepricerSettings(
        max_price_change_percent=float(
            settings_map.get("max_price_change_percent", settings.max_price_change_percent)
        ),
        step_up_type=str(
            settings_map.get("step_up_type", settings.step_up_type)
            or settings.step_up_type
        ).lower(),
        step_up_value=float(
            settings_map.get(
                "step_up_value",
                settings_map.get("step_up_percentage", settings.step_up_value),
            )
        ),
        step_up_interval_hours=float(
            settings_map.get("step_up_interval_hours", settings.step_up_interval_hours)
        ),
    )
    scheduler = getattr(request.app.state, "scheduler", None)
    health_details = {}
    if scheduler:
        health_details = {
            "last_runs": {k: v.isoformat() for k, v in scheduler.last_runs.items()},
            "stats": scheduler.stats,
        }
    health = SystemHealth(status="ok", timestamp=datetime.utcnow(), details=health_details)
    return DashboardPayload(metrics=metrics, health=health, alerts=alerts, settings=repricer_settings)
