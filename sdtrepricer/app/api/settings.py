"""Settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..models import SystemSetting
from ..schemas import RepricerSettings

router = APIRouter()


SETTING_KEYS = {
    "max_price_change_percent": "max_price_change_percent",
    "step_up_percentage": "step_up_percentage",
    "step_up_interval_hours": "step_up_interval_hours",
}


@router.get("/settings", response_model=RepricerSettings)
async def read_settings(session: AsyncSession = Depends(get_db)) -> RepricerSettings:
    settings_rows = (await session.execute(select(SystemSetting))).scalars().all()
    mapping = {setting.key: setting.value for setting in settings_rows}
    try:
        return RepricerSettings(
            max_price_change_percent=float(mapping.get("max_price_change_percent", 20.0)),
            step_up_percentage=float(mapping.get("step_up_percentage", 2.0)),
            step_up_interval_hours=int(mapping.get("step_up_interval_hours", 6)),
        )
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/settings", response_model=RepricerSettings)
async def update_settings(
    payload: RepricerSettings,
    session: AsyncSession = Depends(get_db),
) -> RepricerSettings:
    for key, value in payload.model_dump().items():
        if key not in SETTING_KEYS:
            continue
        existing = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if existing:
            existing.value = str(value)
        else:
            session.add(SystemSetting(key=key, value=str(value)))
    await session.commit()
    return payload
