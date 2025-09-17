"""Utility helpers for alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import logger
from ..models import Alert, AlertSeverity


async def create_alert(
    session: AsyncSession,
    message: str,
    severity: AlertSeverity = AlertSeverity.WARNING,
    metadata: dict[str, Any] | None = None,
) -> Alert:
    alert = Alert(
        message=message,
        severity=severity.value,
        metadata_payload=metadata,
        created_at=datetime.utcnow(),
    )
    session.add(alert)
    await session.flush()
    logger.warning("Alert issued: %s (%s)", message, severity.value)
    return alert
