"""Report endpoint: figures of the last days for the Raporlar page."""

from fastapi import APIRouter, Query

from ..anomaly_service import anomaly_service
from ..event_journal import event_journal
from ..reports import MAX_DAYS, build_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/summary")
async def summary(days: int = Query(7, ge=1, le=MAX_DAYS, description="Calendar days, today included")):
    """Event counts by day, rule and camera, the operator's decisions and how often the summaries agreed."""
    entries = event_journal.list(limit=10 ** 9)
    return {"success": True, "report": build_report(entries, days, capacity=int(anomaly_service.max_stored_clips))}
