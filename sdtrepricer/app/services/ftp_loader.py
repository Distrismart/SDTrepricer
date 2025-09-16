"""Load pricing floors from hourly FTP drops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..core.config import settings
from ..core.logging import logger


@dataclass
class FloorPriceRecord:
    """Floor price entry parsed from FTP feed."""

    sku: str
    asin: str
    min_price: float
    min_business_price: float | None


class FTPFeedLoader:
    """Load and validate hourly CSV feeds."""

    def __init__(self, base_path: str | Path | None = None) -> None:
        self.base_path = Path(base_path or settings.ftp_root)

    def _resolve_file(self, marketplace_code: str) -> Path:
        path = self.base_path / f"{marketplace_code.lower()}_floor_prices.csv"
        return path

    def validate_freshness(self, marketplace_code: str) -> bool:
        path = self._resolve_file(marketplace_code)
        if not path.exists():
            logger.warning("FTP feed missing for %s", marketplace_code)
            return False
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        is_fresh = datetime.utcnow() - modified < timedelta(minutes=settings.ftp_stale_threshold_minutes)
        if not is_fresh:
            logger.warning("FTP feed stale for %s (last modified %s)", marketplace_code, modified)
        return is_fresh

    def load(self, marketplace_code: str) -> Iterable[FloorPriceRecord]:
        path = self._resolve_file(marketplace_code)
        if not path.exists():
            raise FileNotFoundError(f"FTP feed missing for {marketplace_code}")
        try:
            df = pd.read_csv(path)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Failed to load FTP feed %s: %s", path, exc)
            raise
        required_columns = {"SKU", "ASIN", "MIN_PRICE"}
        if missing := required_columns - set(df.columns):
            raise ValueError(f"Missing columns in feed: {missing}")
        for row in df.itertuples():
            yield FloorPriceRecord(
                sku=str(row.SKU),
                asin=str(row.ASIN),
                min_price=float(row.MIN_PRICE),
                min_business_price=float(row.MIN_BUSINESS_PRICE)
                if "MIN_BUSINESS_PRICE" in df.columns and not pd.isna(row.MIN_BUSINESS_PRICE)
                else None,
            )
