"""Settings endpoints. A saved change is applied to the running services immediately."""

from typing import Any, Dict

from fastapi import APIRouter

from ..anomaly_service import anomaly_service
from ..live_detection_service import live_detection_service
from ..settings_service import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _apply(settings: Dict[str, Any]) -> Dict[str, Any]:
    anomaly_service.reload_settings(settings)
    live_detection_service.reload_settings()
    return {"success": True, "settings": settings}


@router.get("")
async def get_settings():
    return {"success": True, "settings": settings_service.get_all()}


@router.post("")
async def update_settings(changes: Dict[str, Any]):
    """Merges the given values into the settings; out-of-range values are clamped by the service."""
    return _apply(settings_service.update(changes))


@router.post("/reset")
async def reset_settings():
    return _apply(settings_service.reset_defaults())
