"""Live analysis endpoints: per-camera state for the wall and the obstacle / change zones."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..anomaly_service import anomaly_service
from ..camera_service import camera_service
from ..change_detector import change_detector
from ..live_detection_service import live_detection_service
from ..rules_service import rules_service

router = APIRouter(prefix="/api", tags=["live"])


@router.get("/live/state")
async def live_state():
    """Everything the live wall needs in one round trip: anomaly scores, stream health, rule detections."""
    return {
        "success": True,
        "fleet": anomaly_service.get_fleet_summary(),
        "detections": live_detection_service.get_detections(),
        "detector_ready": live_detection_service.detector_ready,
    }


@router.get("/cameras/{camera_id}/live-detections")
async def camera_detections(camera_id: str):
    """Current rule detections of one camera."""
    return {"success": True, "data": live_detection_service.get_detections(camera_id=camera_id)}


@router.get("/change-detection/{camera_id}/{zone_id}")
async def change_zone_state(camera_id: str, zone_id: str):
    state = change_detector.get_zone_state(camera_id, zone_id)
    if not state:
        raise HTTPException(status_code=404, detail="Bu bölge için referans görüntü yok.")
    return {"success": True, "state": state}


@router.post("/change-detection/{camera_id}/{zone_id}/capture-reference")
async def capture_reference(
    camera_id: str,
    zone_id: str,
    zone_name: Optional[str] = None,
    description: Optional[str] = None,
):
    """
    Stores the current live frame as the "clear" reference of an obstacle / change zone.
    Call it once while the monitored area is known to be free.
    """
    if not camera_service.get_by_id(camera_id):
        raise HTTPException(status_code=404, detail="Kamera bulunamadı.")

    # Only a real live frame is acceptable: a placeholder or frozen picture would calibrate
    # the zone against garbage and raise permanent false alarms.
    worker = camera_service.get_worker(camera_id)
    frame = worker.get_bgr_frame(touch=True) if worker and worker.is_live() else None
    if frame is None:
        raise HTTPException(status_code=422, detail="Bu kameradan canlı görüntü alınamadı. Kamera bağlantısını kontrol edin.")

    zone = next(
        (z for rule in rules_service.get_all(camera_id=camera_id) for z in rule.get("zones", []) if z.get("id") == zone_id),
        None,
    )
    if zone is None:
        raise HTTPException(status_code=404, detail="Bölge bulunamadı.")
    points = zone.get("points", [])
    if len(points) < 3:
        raise HTTPException(status_code=422, detail="Bölgenin en az 3 köşesi olmalıdır.")

    saved = change_detector.capture_reference(
        camera_id=camera_id,
        zone_id=zone_id,
        frame_bgr=frame,
        points_normalized=points,
        zone_name=zone_name or zone.get("name", ""),
        description=description or zone.get("description", ""),
    )
    if not saved:
        raise HTTPException(status_code=422, detail="Referans alınamadı: bölge çok küçük veya geçersiz.")
    return {"success": True, "camera_id": camera_id, "zone_id": zone_id}


@router.delete("/change-detection/{camera_id}/{zone_id}/reference")
async def delete_reference(camera_id: str, zone_id: str):
    """Removes the stored reference; the zone is not evaluated until a new one is captured."""
    change_detector.delete_reference(camera_id, zone_id)
    return {"success": True}
