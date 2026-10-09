"""Event endpoints: the journal of recorded incidents, their evidence files and the live feed."""

import asyncio
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .. import evidence_store
from ..anomaly_service import anomaly_service
from ..camera_service import camera_service
from ..event_journal import event_journal
from ..event_stream import event_stream
from ..paths import SHUTTING_DOWN
from .schemas import OperatorLabelRequest, SimulateAnomalyRequest

router = APIRouter(prefix="/api/anomaly", tags=["events"])

MAX_JOURNAL_LIMIT = 2000
KEEPALIVE_AFTER_IDLE_SEC = 15
CLIP_READY_WAIT_STEPS = 30  # x 0.1 s: a clip opened right after the incident may still be encoding
SNAPSHOT_CACHE = {"Cache-Control": "private, max-age=604800"}  # the URL carries a version stamp


@router.get("/status")
async def fleet_status():
    """Current anomaly state and stream health of every camera."""
    return anomaly_service.get_fleet_summary()


@router.get("/stats")
async def journal_stats():
    """Counters of the journal (by level and by operator verdict)."""
    return {"success": True, "stats": event_journal.stats()}


@router.get("/journal")
async def journal(
    camera_id: Optional[str] = None,
    tier: Optional[str] = None,
    operator_label: Optional[str] = None,
    limit: int = 250,
):
    """Recorded incidents, newest first."""
    entries = event_journal.list(
        camera_id=camera_id,
        tier=tier,
        operator_label=operator_label,
        limit=max(1, min(limit, MAX_JOURNAL_LIMIT)),
    )
    return {"success": True, "count": len(entries), "stats": event_journal.stats(), "journal": entries}


@router.post("/clear")
async def clear_journal():
    """Deletes every incident together with its clip and snapshot."""
    await asyncio.to_thread(anomaly_service.clear_events)
    return {"success": True}


@router.post("/simulate")
async def simulate(req: SimulateAnomalyRequest):
    """Records an incident with the given score on a camera (for demonstrations and tests)."""
    if not camera_service.get_by_id(req.camera_id):
        raise HTTPException(status_code=404, detail="Kamera bulunamadı.")
    return {"success": True, "entry": anomaly_service.simulate_anomaly(camera_id=req.camera_id, score=req.score)}


@router.get("/events-stream")
async def events_stream(request: Request):
    """Server-sent events: new and updated incidents are pushed to the open pages as they happen."""

    async def generate():
        queue = event_stream.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'connected', 'time': time.time()})}\n\n"
            idle_sec = 0
            while not SHUTTING_DOWN.is_set():
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=1.0)
                    idle_sec = 0
                except asyncio.TimeoutError:
                    idle_sec += 1
                    if idle_sec >= KEEPALIVE_AFTER_IDLE_SEC:
                        idle_sec = 0
                        yield ": keep-alive\n\n"
        finally:
            event_stream.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/storage")
async def storage():
    """Disk usage of clips and snapshots, including files no incident refers to."""
    return await asyncio.to_thread(anomaly_service.get_storage_stats)


@router.post("/storage/cleanup-orphans")
async def cleanup_orphans():
    """Deletes clips and snapshots that no incident refers to."""
    result = await asyncio.to_thread(anomaly_service.delete_orphan_clips)
    return {"success": True, **result}


@router.api_route("/clips/{filename}", methods=["GET", "HEAD"])
async def clip(filename: str):
    """Incident video (supports range requests, so the player can seek)."""
    safe_name = os.path.basename(filename)
    path = os.path.join(evidence_store.CLIPS_DIR, safe_name)
    encoding_path = os.path.join(evidence_store.CLIPS_DIR, evidence_store.ENCODING_PREFIX + safe_name)

    def ready() -> bool:
        return os.path.exists(path) and os.path.getsize(path) >= evidence_store.MIN_CLIP_BYTES

    for _ in range(CLIP_READY_WAIT_STEPS):
        if ready() or not (os.path.exists(encoding_path) or os.path.exists(path)):
            break
        await asyncio.sleep(0.1)
    if not ready():
        raise HTTPException(status_code=404, detail="Bu olayın videosu yok veya henüz hazır değil.")
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")


@router.api_route("/snapshots/{filename}", methods=["GET", "HEAD"])
async def snapshot(filename: str):
    """Camera frame captured at the moment of an incident."""
    safe_name = os.path.basename(filename)
    path = os.path.join(evidence_store.SNAPSHOTS_DIR, safe_name)
    if not safe_name.endswith(".jpg") or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Bu olayın fotoğrafı yok.")
    return FileResponse(path, media_type="image/jpeg", headers=SNAPSHOT_CACHE)


@router.post("/{entry_id}/label")
async def label(entry_id: str, req: OperatorLabelRequest):
    """Stores the operator's verdict on an incident: 'correct', 'false_positive' or 'unlabeled'."""
    try:
        entry = event_journal.set_label(entry_id, req.label, req.notes or "", req.operator_name or "Operatör")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if entry is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı.")
    return {"success": True, "entry": entry}


@router.post("/{entry_id}/summarize")
async def summarize(entry_id: str):
    """Starts (or restarts) writing the summary of an incident from its clip."""
    result = anomaly_service.summarize_entry(entry_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Özet başlatılamadı."))
    return result


@router.get("/{entry_id}/frames")
async def frames(entry_id: str):
    """Frames sampled evenly from the incident clip."""
    # Decoding the clip is CPU work: keep it off the event loop
    result = await asyncio.to_thread(anomaly_service.get_entry_frames, entry_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Kareler bulunamadı."))
    return result
