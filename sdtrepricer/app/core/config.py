"""Application configuration using pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment settings for the repricer service."""

    model_config = SettingsConfigDict(env_file=(".env",), env_nested_delimiter="__")

    app_name: str = "SDT Repricer"
    environment: Literal["local", "staging", "production"] = "local"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://repricer:repricer@db:5432/repricer"
    ftp_root: str = "./ftp_feeds"
    ftp_stale_threshold_minutes: int = 90
    marketplace_ids: dict[str, str] = {
        "DE": "A1PA6795UKMFR9",
        "FR": "A13V1IB3VIYZZH",
        "NL": "A1805IZSGTT6HS",
        "BE": "AMEN7PMS3EDWL",
        "IT": "APJ6JRA9NG5V4",
    }
    sp_api_client_id: str | None = None
    sp_api_client_secret: str | None = None
    sp_api_refresh_token: str | None = None
    lwa_app_id: str | None = None
    lwa_client_secret: str | None = None
    sp_api_role_arn: str | None = None
    notification_email: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    scheduler_tick_seconds: int = 60
    repricing_batch_size: int = 40
    repricing_concurrency: int = 8
    max_price_change_percent: float = 20.0
    step_up_type: Literal["percentage", "absolute"] = "percentage"
    step_up_value: float = 2.0
    step_up_interval_hours: float = 6.0
    sp_api_endpoint: str = "https://sellingpartnerapi-eu.amazon.com"
    test_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()


settings = get_settings()
