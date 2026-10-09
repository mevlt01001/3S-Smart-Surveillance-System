"""
Report figures: what happened over the last days, counted from the event journal.

Pure functions over journal entries - no state, no files, no imports from the services - so
the numbers can be checked without a running system. Demonstration events ("sim_...") are left out.
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

Entry = Dict[str, Any]
MAX_DAYS = 90
MOVEMENT = "Olağandışı hareket"


def is_rule_violation(entry: Entry) -> bool:
    """Same test as the journal's; repeated here so that this module needs no running service."""
    return str(entry.get("id", "")).startswith("rule_")


def _decisions(entries: List[Entry]) -> Dict[str, int]:
    correct = sum(1 for entry in entries if entry.get("operator_label") == "correct")
    false_positive = sum(1 for entry in entries if entry.get("operator_label") == "false_positive")
    return {"events": len(entries), "correct": correct, "false_positive": false_positive,
            "unreviewed": len(entries) - correct - false_positive}


def _lasted(entry: Entry, now: float) -> float:
    """How long the event lasted; a violation that is still running has lasted until now."""
    if entry.get("is_ongoing"):
        return max(0.0, now - float(entry.get("timestamp") or now))
    return float(entry.get("incident_sec") or entry.get("duration_sec") or 0.0)


def build_report(entries: List[Entry], days: int, now: Optional[float] = None, capacity: int = 0) -> Dict[str, Any]:
    """
    The report of the last `days` calendar days (1 = today since midnight), local time.
    `capacity` is the largest number of events the journal keeps: when the journal is full and
    its oldest event is younger than the period, the report says that it is incomplete.
    """
    days = max(1, min(MAX_DAYS, int(days)))
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    real = [entry for entry in entries if not str(entry.get("id", "")).startswith("sim_")]
    period = [entry for entry in real if start.timestamp() <= float(entry.get("timestamp") or 0) <= now]
    rule_events = [entry for entry in period if is_rule_violation(entry)]
    movement_events = [entry for entry in period if not is_rule_violation(entry)]

    # One bar per hour for a single day, one per day otherwise
    if days == 1:
        buckets = [{"label": f"{hour:02d}:00", "rule": 0, "movement": 0} for hour in range(24)]
        index_of = lambda moment: moment.hour  # noqa: E731
    else:
        buckets = [{"label": (start + timedelta(days=offset)).strftime("%d.%m"), "rule": 0, "movement": 0}
                   for offset in range(days)]
        index_of = lambda moment: (moment.replace(hour=0, minute=0, second=0, microsecond=0) - start).days  # noqa: E731
    for entry in period:
        bucket = buckets[index_of(datetime.fromtimestamp(float(entry["timestamp"])))]
        bucket["rule" if is_rule_violation(entry) else "movement"] += 1

    def grouped(items: List[Entry], key) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Entry]] = {}
        for entry in items:
            groups.setdefault(key(entry), []).append(entry)
        rows = [dict(name=name, **_decisions(group), total_sec=round(sum(_lasted(entry, now) for entry in group), 1),
                     rule=sum(1 for entry in group if is_rule_violation(entry)),
                     ongoing=sum(1 for entry in group if entry.get("is_ongoing")))
                for name, group in groups.items()]
        return sorted(rows, key=lambda row: (-row["events"], row["name"]))

    # How often the summary's own verdict matched the operator's decision
    judged = [entry for entry in period
              if entry.get("operator_label") in ("correct", "false_positive") and entry.get("ai_verdict") in ("confirmed", "normal")]
    agreed = sum(1 for entry in judged
                 if (entry["operator_label"] == "correct") == (entry["ai_verdict"] == "confirmed"))

    totals = _decisions(period)
    reviewed = totals["correct"] + totals["false_positive"]
    oldest = min((float(entry.get("timestamp") or now) for entry in real), default=None)
    return {
        "days": days,
        "from": start.timestamp(),
        "to": now,
        "from_text": start.strftime("%d.%m.%Y"),
        "to_text": datetime.fromtimestamp(now).strftime("%d.%m.%Y %H:%M"),
        "totals": dict(
            totals,
            rule=len(rule_events),
            movement=len(movement_events),
            false_alarm_pct=round(100.0 * totals["false_positive"] / reviewed, 1) if reviewed else None,
        ),
        "buckets": buckets,
        "by_rule": grouped(rule_events, lambda entry: entry.get("rule_title") or "Kural ihlali"),
        "by_camera": grouped(period, lambda entry: entry.get("camera_name") or entry.get("camera_id") or "Kamera"),
        "summary_verdict": {"compared": len(judged), "agreed": agreed},
        # The journal is a fixed-size list: older events may already have been dropped
        "incomplete": bool(capacity and len(entries) >= capacity and oldest is not None and oldest > start.timestamp()),
        "movement_label": MOVEMENT,
    }
