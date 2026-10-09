"""System status and network discovery endpoints."""

import time

from fastapi import APIRouter

from ..onvif_core import run_multi_nic_ws_discovery
from ..system_stats import get_system_telemetry

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health():
    """Cheap liveness probe."""
    return {"ok": True, "time": time.time()}


@router.get("/system/stats")
async def system_stats():
    """Analysis server state, measured inference times and GPU telemetry."""
    return await get_system_telemetry()


@router.post("/onvif/scan")
async def scan_network(timeout: float = 3.0):
    """Looks for ONVIF cameras on every active network interface (WS-Discovery)."""
    devices = await run_multi_nic_ws_discovery(timeout=timeout)
    return {"success": True, "count": len(devices), "devices": devices}
