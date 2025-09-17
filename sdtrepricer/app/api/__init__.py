"""API router aggregator."""

from fastapi import APIRouter

from . import actions, dashboard, settings, test_data

api_router = APIRouter()
api_router.include_router(dashboard.router, tags=["dashboard"], prefix="/metrics")
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(actions.router, tags=["actions"], prefix="/actions")
api_router.include_router(test_data.router, tags=["test-data"], prefix="/test-data")
