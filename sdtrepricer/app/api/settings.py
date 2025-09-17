"""Settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..dependencies import get_db
from ..models import SystemSetting
from ..schemas import RepricerSettings

router = APIRouter()


SETTING_KEYS = {
    "max_price_change_percent": "max_price_change_percent",
    "step_up_type": "step_up_type",
    "step_up_value": "step_up_value",
    "step_up_interval_hours": "step_up_interval_hours",
    "test_mode": "test_mode",
}


@router.get("/settings", response_model=RepricerSettings)
async def read_settings(session: AsyncSession = Depends(get_db)) -> RepricerSettings:
    settings_rows = (await session.execute(select(SystemSetting))).scalars().all()
    mapping = {setting.key: setting.value for setting in settings_rows}
    try:
        test_mode_value = mapping.get("test_mode")
        return RepricerSettings(
            max_price_change_percent=float(
                mapping.get("max_price_change_percent", settings.max_price_change_percent)
            ),
            step_up_type=str(
                mapping.get("step_up_type", settings.step_up_type)
                or settings.step_up_type
            ).lower(),
            step_up_value=float(
                mapping.get(
                    "step_up_value",
                    mapping.get("step_up_percentage", settings.step_up_value),
                )
            ),
            step_up_interval_hours=float(
                mapping.get("step_up_interval_hours", settings.step_up_interval_hours)
            ),
            test_mode=(
                settings.test_mode
                if test_mode_value is None
                else str(test_mode_value).lower() in {"1", "true", "yes", "on"}
            ),
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
        if isinstance(value, bool):
            stored_value = "true" if value else "false"
        else:
            stored_value = str(value)
        if existing:
            existing.value = stored_value
        else:
            session.add(SystemSetting(key=key, value=stored_value))
    await session.commit()
    return payload
