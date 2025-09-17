"""FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from .api import api_router
from .core.config import settings
from .core.database import get_session, init_db
from .core.logging import configure_logging
from .migrations import run_migrations
from .models import Marketplace
from .services.scheduler import RepricingScheduler

app = FastAPI(title=settings.app_name, version="0.1.0")
configure_logging()

static_dir = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


async def ensure_marketplaces() -> None:
    async with get_session() as session:
        existing_codes = set((await session.scalars(select(Marketplace.code))).all())
        for code, marketplace_id in settings.marketplace_ids.items():
            if code in existing_codes:
                continue
            session.add(
                Marketplace(
                    code=code,
                    name={
                        "DE": "Germany",
                        "FR": "France",
                        "NL": "Netherlands",
                        "BE": "Belgium",
                        "IT": "Italy",
                    }.get(code, code),
                    amazon_id=marketplace_id,
                )
            )
        await session.commit()


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    await run_migrations()
    await ensure_marketplaces()
    scheduler = RepricingScheduler()
    app.state.scheduler = scheduler
    await scheduler.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    scheduler: RepricingScheduler | None = getattr(app.state, "scheduler", None)
    if scheduler:
        await scheduler.stop()


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request})


app.include_router(api_router, prefix=settings.api_prefix)


__all__ = ["app"]
