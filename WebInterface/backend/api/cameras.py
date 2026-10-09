"""Camera endpoints: the camera list, registration, and live pictures."""

import asyncio
import ipaddress

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..camera_service import camera_service
from ..change_detector import change_detector
from ..rules_service import rules_service
from .schemas import AddCameraRequest, UpdateCameraRequest

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

MAX_STREAM_FPS = 60.0
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


def _require_camera(camera_id: str) -> dict:
    camera = camera_service.get_by_id(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Kamera bulunamadı.")
    return camera


@router.get("")
async def list_cameras():
    cameras = [camera_service.public_view(camera) for camera in camera_service.get_all()]
    return {"success": True, "count": len(cameras), "cameras": cameras}


@router.post("/add")
async def add_camera(req: AddCameraRequest):
    """Connects to the camera over ONVIF, reads its stream address and registers it."""
    ip = req.ip.strip()
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        raise HTTPException(status_code=422, detail="Geçerli bir IPv4 adresi girin (örn. 192.168.1.150).")
    if not (1 <= req.port <= 65535) or not (1 <= req.rtsp_port <= 65535):
        raise HTTPException(status_code=422, detail="Port değeri 1-65535 aralığında olmalıdır.")

    camera = await camera_service.probe_and_register(
        ip=ip,
        port=req.port,
        username=(req.username or "").strip(),
        password=(req.password or "").strip(),
        custom_name=(req.name or "").strip(),
        rtsp_port=req.rtsp_port,
    )
    return {"success": True, "camera": camera_service.public_view(camera)}


@router.put("/{camera_id}")
async def update_camera(camera_id: str, req: UpdateCameraRequest):
    """Changes the display name and the description of a camera."""
    updated = camera_service.update_camera(camera_id=camera_id, name=req.name, description=req.description)
    if not updated:
        raise HTTPException(status_code=404, detail="Kamera bulunamadı.")
    return {"success": True, "camera": camera_service.public_view(updated)}


@router.delete("/{camera_id}")
async def delete_camera(camera_id: str):
    """Removes a camera together with everything that only makes sense with it."""
    if not camera_service.delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Kamera bulunamadı.")
    removed_rules = rules_service.delete_rules_for_camera(camera_id)
    change_detector.delete_camera_references(camera_id)
    return {"success": True, "removed_rules": removed_rules}


@router.post("/{camera_id}/reconnect")
async def reconnect_camera(camera_id: str):
    """Probes the camera again with its stored credentials."""
    camera = _require_camera(camera_id)
    updated = await camera_service.probe_and_register(
        ip=camera["ip"],
        port=camera["port"],
        username=camera.get("username", ""),
        password=camera.get("password", ""),
        custom_name=camera.get("name", ""),
        rtsp_port=camera.get("rtsp_port", 554),
    )
    return {"success": True, "camera": camera_service.public_view(updated)}


@router.api_route("/{camera_id}/snapshot", methods=["GET", "HEAD"])
async def snapshot(camera_id: str, request: Request):
    """Current picture of the camera, or a "no signal" card. Always answers 200 so polling stays simple."""
    image_bytes, media_type = await camera_service.get_camera_snapshot(camera_id)
    headers = {**_NO_CACHE, "Content-Length": str(len(image_bytes))}
    body = b"" if request.method == "HEAD" else image_bytes
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/{camera_id}/stream")
async def mjpeg_stream(camera_id: str, request: Request):
    """Continuous MJPEG stream (multipart/x-mixed-replace) for clients that cannot use the WebSocket."""
    return StreamingResponse(
        camera_service.mjpeg_stream_generator(camera_id, request=request),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={**_NO_CACHE, "Connection": "close"},
    )


@router.websocket("/{camera_id}/ws")
async def frame_socket(websocket: WebSocket, camera_id: str, fps: float = 0.0):
    """
    Live binary JPEG frames. A frame is pushed the moment the camera worker decodes it, the
    newest frame always wins (a slow client skips frames instead of falling behind) and a
    "no signal" card is sent while the camera is down. `?fps=N` caps the delivery rate.
    """
    await websocket.accept()
    if not camera_service.get_by_id(camera_id):
        await websocket.close(code=1008, reason="Camera Not Found")
        return

    async def drain_client():
        # Notices a closed browser tab immediately instead of on the next failed send
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    receiver = asyncio.create_task(drain_client())
    try:
        async for frame in camera_service.iter_frames(camera_id, max_fps=max(0.0, min(fps, MAX_STREAM_FPS))):
            if receiver.done():
                break
            await websocket.send_bytes(frame)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass  # the client went away
    finally:
        receiver.cancel()
        try:
            await websocket.close()
        except Exception:
            pass  # already closed
