"""
FastAPI Server for Commercial Surveillance System WebInterface
Serves REST APIs for ONVIF Discovery, Fleet Management, Live Snapshots, and System Stats.
Mounts frontend static assets.
"""

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .camera_service import CameraService
from .rules_service import RulesService
from .events_service import EventsService
from .onvif_core import run_multi_nic_ws_discovery, get_active_ipv4_interfaces
from .system_stats import get_system_telemetry

app = FastAPI(title="AegisVision Commercial Surveillance System API", version="1.0.0")

# Enable CORS for local development and client flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instantiate Fleet, Rules, and Events Managers
camera_service = CameraService()
rules_service = RulesService()
events_service = EventsService()

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


# Request Schemas
class AddCameraRequest(BaseModel):
    ip: str = Field(..., description="Camera IP Address")
    port: int = Field(80, description="ONVIF HTTP Port (typically 80, 8080, 8899)")
    username: Optional[str] = Field("", description="ONVIF Username")
    password: Optional[str] = Field("", description="ONVIF Password")
    name: Optional[str] = Field("", description="Custom Display Name")
    rtsp_port: int = Field(554, description="RTSP Port (default 554)")


class UpdateCameraRequest(BaseModel):
    name: Optional[str] = Field(None, description="Camera display name")
    description: Optional[str] = Field(None, description="Camera purpose and security description")


class CreateRuleRequest(BaseModel):
    title: str = Field(..., description="Rule Title (e.g. Giriş Kapısı İhlali)")
    scope: str = Field("camera", description="'camera' (camera-wise) or 'system' (system-wise)")
    camera_id: Optional[str] = Field(None, description="Camera ID if scope is camera")
    camera_name: Optional[str] = Field(None, description="Camera display name")
    severity: str = Field("warning", description="Severity: 'critical', 'warning', or 'info'")
    description: str = Field("", description="Natural language prompt / description of rule")
    zones: Optional[list] = Field(default_factory=list, description="Per-zone rules [{id, name, description, severity, actions, points}]")
    actions: Optional[list] = Field(default_factory=list, description="Trigger actions")
    assignee: Optional[dict] = Field(None, description="1. Derece Bildirim Sorumlusu")
    escalation: Optional[dict] = Field(None, description="2. Derece Eskalasyon Yetkilisi")


class UpdateRuleRequest(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    zones: Optional[list] = None
    actions: Optional[list] = None
    assignee: Optional[dict] = None
    escalation: Optional[dict] = None


class ResolveEventRequest(BaseModel):
    operator_name: Optional[str] = "Nöbetçi Operatör"
    force_override: Optional[bool] = False
    note: Optional[str] = ""



# --- API Routes ---

@app.get("/api/system/stats")
async def api_system_stats():
    """Returns GPU metrics and Triton Server health status."""
    return await get_system_telemetry()


@app.get("/api/onvif/interfaces")
async def api_get_interfaces():
    """Returns all active physical network interfaces used for WS-Discovery."""
    return {"interfaces": get_active_ipv4_interfaces()}


@app.post("/api/onvif/scan")
async def api_onvif_scan(timeout: float = 3.0):
    """
    Executes standard WS-Discovery multicast probe across all active physical interfaces.
    Returns all detected ONVIF devices.
    """
    devices = await run_multi_nic_ws_discovery(timeout=timeout)
    return {
        "success": True,
        "count": len(devices),
        "devices": devices
    }


@app.get("/api/cameras")
async def api_get_cameras():
    """Returns all registered cameras in fleet."""
    cameras = camera_service.get_all()
    return {
        "success": True,
        "count": len(cameras),
        "cameras": cameras
    }


@app.post("/api/cameras/add")
async def api_add_camera(req: AddCameraRequest):
    """
    Connects to camera via ONVIF, syncs time, fetches profiles/RTSP URIs,
    and registers it to the fleet.
    """
    camera = await camera_service.probe_and_register(
        ip=req.ip.strip(),
        port=req.port,
        username=req.username.strip() if req.username else "",
        password=req.password.strip() if req.password else "",
        custom_name=req.name.strip() if req.name else "",
        rtsp_port=req.rtsp_port
    )
    return {
        "success": True,
        "camera": camera
    }


@app.delete("/api/cameras/{camera_id}")
async def api_delete_camera(camera_id: str):
    """Removes a camera from fleet."""
    removed = camera_service.delete_camera(camera_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"success": True, "message": "Camera deleted"}


@app.put("/api/cameras/{camera_id}")
async def api_update_camera(camera_id: str, req: UpdateCameraRequest):
    """Updates camera display name and descriptive purpose/rules context."""
    updated = camera_service.update_camera(
        camera_id=camera_id,
        name=req.name,
        description=req.description
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"success": True, "camera": updated}


@app.post("/api/cameras/{camera_id}/reconnect")
async def api_reconnect_camera(camera_id: str):
    """Retriggers ONVIF probe and refreshes device status."""
    existing = camera_service.get_by_id(camera_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    updated = await camera_service.probe_and_register(
        ip=existing["ip"],
        port=existing["port"],
        username=existing.get("username", ""),
        password=existing.get("password", ""),
        custom_name=existing.get("name", ""),
        rtsp_port=existing.get("rtsp_port", 554)
    )
    return {"success": True, "camera": updated}


@app.api_route("/api/cameras/{camera_id}/snapshot", methods=["GET", "HEAD"])
async def api_get_snapshot(camera_id: str, request: Request):
    """
    Returns live JPEG snapshot from the camera or fallback HUD graphic.
    Always returns HTTP 200 with no-cache headers for smooth frontend polling.
    Supports HEAD requests for browser preloading without 405 error.
    """
    image_bytes, media_type = await camera_service.get_camera_snapshot(camera_id)
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Content-Length": str(len(image_bytes))
    }
    if request.method == "HEAD":
        return Response(content=b"", media_type=media_type, headers=headers)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers=headers
    )


# --- Spatial Rules & Zones Endpoints ---

@app.get("/api/rules")
async def api_get_rules(camera_id: Optional[str] = None):
    """Returns all defined rules, optionally filtered by camera."""
    rules = rules_service.get_all(camera_id=camera_id)
    return {
        "success": True,
        "count": len(rules),
        "rules": rules
    }


@app.post("/api/rules")
async def api_create_rule(req: CreateRuleRequest):
    """Creates a new rule with per-zone rules, assignee, and escalation settings."""
    rule = rules_service.create_rule(
        title=req.title,
        scope=req.scope,
        camera_id=req.camera_id,
        camera_name=req.camera_name,
        severity=req.severity,
        description=req.description,
        zones=req.zones,
        actions=req.actions,
        assignee=req.assignee,
        escalation=req.escalation
    )
    return {
        "success": True,
        "rule": rule
    }


@app.get("/api/rules/{rule_id}")
async def api_get_rule_by_id(rule_id: str):
    """Gets details of a single rule."""
    rule = rules_service.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True, "rule": rule}


@app.put("/api/rules/{rule_id}")
async def api_update_rule(rule_id: str, req: UpdateRuleRequest):
    """Updates rule attributes (enable/disable, polygon, severity, etc.)."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = rules_service.update_rule(rule_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True, "rule": updated}


@app.delete("/api/rules/{rule_id}")
async def api_delete_rule(rule_id: str):
    """Deletes a rule."""
    deleted = rules_service.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True, "message": "Rule deleted"}


# --- Incident & Events Management Endpoints ---

@app.get("/api/events")
async def api_get_events(status: Optional[str] = None):
    """Returns active and historical incident records."""
    events = events_service.get_all(status=status)
    return {
        "success": True,
        "count": len(events),
        "events": events
    }


@app.get("/api/events/{event_id}")
async def api_get_event(event_id: str):
    """Returns a single incident record."""
    evt = events_service.get_by_id(event_id)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True, "event": evt}


@app.post("/api/events/{event_id}/resolve")
async def api_resolve_event(event_id: str, req: ResolveEventRequest):
    """
    Attempts to resolve an incident with live AI verification loop.
    Rejects closure if violation is still present on camera unless force_override is True.
    """
    res = events_service.attempt_resolve(
        event_id=event_id,
        operator_name=req.operator_name or "Operatör",
        force_override=req.force_override or False,
        resolution_note=req.note or ""
    )
    return res


@app.post("/api/events/simulate")
async def api_simulate_event(camera_id: Optional[str] = None):
    """Simulates a live security/safety violation event based on active rules."""
    rules = rules_service.get_all(camera_id=camera_id)
    target_rule = None
    target_zone = None

    for r in rules:
        if r.get("zones") and len(r["zones"]) > 0:
            target_rule = r
            target_zone = r["zones"][0]
            break

    if not target_rule or not target_zone:
        # Fallback dummy event
        target_rule = {
            "id": "rule_depo_isg",
            "title": "Depo İSG Denetimi",
            "camera_id": camera_id or "cam_10_23_247_54_8893",
            "camera_name": "Depo Kuzey",
            "severity": "warning",
            "assignee": {"name": "Saha Şefi Ali", "role": "Güvenlik Sorumlusu", "phone": "104"},
            "escalation": {"supervisor_name": "İSG Müdürü", "timeout_minutes": 5}
        }
        target_zone = {"id": "zone_work", "name": "Çalışma Alanı"}

    evt = events_service.create_event(
        rule_id=target_rule["id"],
        rule_title=target_rule["title"],
        camera_id=target_rule.get("camera_id") or "cam_10_23_247_54_8893",
        camera_name=target_rule.get("camera_name") or "Depo Kuzey",
        zone_id=target_zone.get("id", "zone_1"),
        zone_name=target_zone.get("name", "Çalışma Alanı"),
        violation_type="İSG İhlali: Bölgede Baret / Yelek Yok",
        description=f"{target_zone.get('name', 'Bölge')} içerisinde güvenlik donanımı (yelek/baret) eksik personel tespit edildi.",
        severity=target_rule.get("severity", "warning"),
        assignee=target_rule.get("assignee"),
        escalation=target_rule.get("escalation")
    )
    return {"success": True, "event": evt}


# --- Frontend Static Files Serving ---

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index():
        index_file = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "AegisVision Backend Active. Frontend index.html not yet built."}
