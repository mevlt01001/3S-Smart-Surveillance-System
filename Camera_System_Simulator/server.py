"""
AEGIS-PRO Enterprise CCTV & NVR Simulation Server
FastAPI backend providing REST APIs, WebSockets telemetry, RTSP/WebRTC coordination,
and real 5-frame segment local NVR storage playback.
PTZ and fake AI bounding box code has been completely destroyed.
"""

import os
import io
import time
import json
import asyncio
import logging
from typing import Dict, Any, Optional
import httpx

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.catalog import get_catalog, get_set_metadata
from core.streamer import StreamManager
from core.playback import PlaybackEngine
from core.telemetry import TelemetryEngine
from core.storage import storage_manager, RECORDINGS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("NVRServer")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

app = FastAPI(
    title="AEGIS-PRO Surveillance NVR & VMS Simulator",
    version="4.85.100",
    description="Enterprise-grade IP Camera & Local NVR Disk Simulator"
)

# CORS Middleware allowing cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global core engines
stream_manager = StreamManager(initial_set="set_1")
playback_engine = PlaybackEngine()
telemetry_engine = TelemetryEngine()

# Connected WebSocket clients
ws_clients: set[WebSocket] = set()


class SetSwitchRequest(BaseModel):
    set_id: str


class StorageConfigRequest(BaseModel):
    max_storage_mb: float


@app.on_event("startup")
async def startup_event():
    logger.info("Initializing AEGIS-PRO Surveillance NVR Core...")
    # Start MediaMTX streaming server
    stream_manager.start_mediamtx()
    # Start camera streamers for default set (set_1)
    stream_manager.start_cameras()

    # Start background telemetry broadcaster
    asyncio.create_task(broadcast_telemetry_loop())
    logger.info("AEGIS-PRO Surveillance System online and ready.")


@app.on_event("shutdown")
def shutdown_event():
    logger.info("Stopping AEGIS-PRO Surveillance Core...")
    stream_manager.shutdown()


async def broadcast_telemetry_loop():
    """Continuously broadcasts live camera bitrate, FPS, storage quota, and system events."""
    while True:
        try:
            if ws_clients:
                active_cams = stream_manager.get_active_cameras()
                cam_telem = telemetry_engine.get_camera_telemetry(active_cams)
                hw_stats = telemetry_engine.get_system_hardware()
                storage_status = storage_manager.get_status()
                new_event = telemetry_engine.poll_new_event(active_cams)

                payload = {
                    "timestamp": time.time(),
                    "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "hardware": hw_stats,
                    "storage": storage_status,
                    "cameras": cam_telem,
                    "active_set": stream_manager.active_set_id,
                    "new_event": new_event
                }
                msg = json.dumps(payload)
                dead_sockets = set()
                for ws in ws_clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead_sockets.add(ws)
                for ws in dead_sockets:
                    ws_clients.discard(ws)
        except Exception as e:
            logger.debug(f"Telemetry broadcast error: {e}")
        await asyncio.sleep(1.0)


# =========================================================================
# REST API Endpoints
# =========================================================================

@app.get("/api/status")
async def get_system_status():
    """Returns overall NVR system health, storage, and streaming states."""
    status = stream_manager.get_system_status()
    hw = telemetry_engine.get_system_hardware()
    storage = storage_manager.get_status()
    return {
        "status": "OPERATIONAL",
        "system": hw,
        "storage": storage,
        "streaming": status
    }


@app.get("/api/sets")
async def list_sets():
    """Lists all available 11 video sets with technical specifications."""
    cat = get_catalog()
    return {
        "active_set": stream_manager.active_set_id,
        "sets": list(cat.values())
    }


@app.post("/api/sets/active")
async def switch_active_set(req: SetSwitchRequest):
    """Hot-swaps the active video set and resets local recordings."""
    cat = get_catalog()
    if req.set_id not in cat:
        raise HTTPException(status_code=404, detail=f"Set {req.set_id} does not exist.")

    new_meta = stream_manager.switch_set(req.set_id)
    return {
        "message": f"Switched to {req.set_id}",
        "active_set": req.set_id,
        "set_metadata": new_meta
    }


@app.get("/api/cameras")
async def list_cameras():
    """Returns active cameras with RTSP, WebRTC WHEP, and HLS streaming URLs."""
    cams = stream_manager.get_active_cameras()
    return {
        "set_id": stream_manager.active_set_id,
        "camera_count": len(cams),
        "cameras": cams
    }


@app.get("/api/cameras/{cam_id}/snapshot")
async def get_camera_snapshot(cam_id: str):
    """Returns a real-time JPEG snapshot frame from the camera."""
    img_bytes = stream_manager.capture_snapshot(cam_id)
    if not img_bytes:
        raise HTTPException(status_code=404, detail=f"Camera {cam_id} frame unavailable.")
    return Response(content=img_bytes, media_type="image/jpeg")


# =========================================================================
# NVR Local Storage & Synchronized Playback Endpoints
# =========================================================================

@app.get("/api/storage/status")
async def get_storage_status():
    """Returns current disk space, segment count, and ring-buffer health."""
    return storage_manager.get_status()


@app.post("/api/storage/config")
async def set_storage_config(req: StorageConfigRequest):
    """Dynamically modifies the maximum disk storage quota in MB."""
    new_status = storage_manager.set_max_storage_mb(req.max_storage_mb)
    return {
        "message": f"Storage quota updated to {req.max_storage_mb} MB",
        "storage": new_status
    }


@app.get("/api/storage/segment/{cam_id}/{filename}")
async def serve_storage_segment(cam_id: str, filename: str):
    """Streams a genuine 5-frame recorded MP4 segment from local storage."""
    file_path = os.path.join(RECORDINGS_DIR, cam_id, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Segment not found or purged by FIFO buffer.")
    return FileResponse(file_path, media_type="video/mp4")


@app.get("/api/playback/video/{cam_id}")
async def serve_playback_video(cam_id: str, set_id: Optional[str] = None):
    """
    Serves the camera's recorded video file with HTTP 206 Partial Content (Range requests)
    enabling silky-smooth 30/60 fps hardware decoding and instant synchronized seeking.
    """
    target_set = set_id or stream_manager.active_set_id
    filepath = playback_engine.get_camera_recording_source(cam_id, target_set)
    if not filepath or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Recording source not found.")
    return FileResponse(filepath, media_type="video/mp4")


@app.api_route("/api/whep/{cam_id}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
async def whep_proxy(cam_id: str, request: Request):
    """Proxies WebRTC WHEP signaling requests directly to MediaMTX on port 8889."""
    target_url = f"http://127.0.0.1:8889/{cam_id}/whep"
    method = request.method
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
    body = await request.body()

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                content=body
            )
            resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ["content-encoding", "content-length", "transfer-encoding"]}
            return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
        except Exception as e:
            logger.error(f"WHEP proxy error for {cam_id}: {e}")
            raise HTTPException(status_code=502, detail=f"WebRTC engine unreachable: {e}")


@app.get("/api/playback/timeline")
async def get_playback_timeline(set_id: Optional[str] = None):
    """Returns NVR timeline markers derived from genuine local recordings."""
    target_set = set_id or stream_manager.active_set_id
    timeline_data = playback_engine.get_timeline_metadata(target_set)
    return timeline_data


@app.get("/api/playback/sync_seek")
async def sync_seek_playback(offset_sec: float = 0.0):
    """
    Returns the matching 5-frame recorded MP4 segment for every active camera
    at the specified playback time offset, achieving lockstep synchronized seek.
    """
    segments = playback_engine.get_sync_segment_for_offset(offset_sec, stream_manager.active_set_id)
    return {
        "offset_sec": offset_sec,
        "cameras": segments
    }


@app.get("/api/events")
async def get_events():
    """Returns recent surveillance event log."""
    return {
        "count": len(telemetry_engine.get_events()),
        "events": telemetry_engine.get_events()
    }


# =========================================================================
# WebSockets Real-time Channel
# =========================================================================

@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"WebSocket client connected. Active clients: {len(ws_clients)}")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected. Remaining: {len(ws_clients)}")
    except Exception:
        ws_clients.discard(websocket)


# Mount static frontend directory
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
