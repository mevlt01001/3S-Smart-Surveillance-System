"""
Working hours of a rule: the daily time window and the weekdays on which it is checked.

A schedule is a small dictionary, stored with the rule:

    {"start": "22:00", "end": "06:00", "days": [0, 1, 2, 3, 4], "source": "user"}

`days` are weekday numbers, 0 = Monday ... 6 = Sunday. A window whose end is not after its
start runs past midnight and belongs to the day it starts on (Friday 22:00-06:00 covers
Saturday morning). A schedule without `start` and `end` means "always"; `source` tells who
set it: "user" in the rule form, "text" when it was read from the rule's sentence.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
_DAY_NAMES = {"tr": ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
              "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
_WORDS = {"tr": {"every": "Her gün", "weekdays": "Hafta içi", "weekend": "Hafta sonu", "all_day": "Tüm gün"},
          "en": {"every": "Every day", "weekdays": "Weekdays", "weekend": "Weekends", "all_day": "All day"}}
_CLOCK = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


def _clock(value: Any) -> Optional[str]:
    """'7:5' is not a time, '7:05' and '07.05' are; returns 'HH:MM' or None."""
    match = _CLOCK.match(str(value or "").strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def normalize(schedule: Any, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Cleans a schedule that came from the form or from the language model. Returns None when
    there is nothing to keep, a dictionary with only `source` for "always, and that is on
    purpose", and a full schedule otherwise. Unusable values never raise: they mean "always".
    """
    if not isinstance(schedule, dict):
        return None
    source = source or schedule.get("source")
    result: Dict[str, Any] = {"source": source} if source in ("user", "text") else {}
    start = _clock(schedule.get("start"))
    end = _clock("00:00" if str(schedule.get("end")).strip() in ("24:00", "24.00") else schedule.get("end"))
    if start == "00:00" and end == "23:59":
        end = "00:00"  # "the whole day" as models and people tend to write it
    if start and end:
        days = sorted({int(day) for day in (schedule.get("days") or []) if str(day).lstrip("-").isdigit() and 0 <= int(day) <= 6})
        result.update(start=start, end=end, days=days or list(ALL_DAYS))
    return result or None


def has_window(schedule: Optional[Dict[str, Any]]) -> bool:
    return bool(schedule and schedule.get("start") and schedule.get("end"))


def is_active(schedule: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """Is a rule with this schedule to be checked at `now` (default: the current local time)?"""
    if not has_window(schedule):
        return True
    now = now or datetime.now()
    clock = now.strftime("%H:%M")
    start, end, days = schedule["start"], schedule["end"], schedule.get("days") or ALL_DAYS
    if start < end:
        return now.weekday() in days and start <= clock < end
    # Past midnight (or the whole day when start == end): the early hours belong to the day before
    if clock >= start:
        return now.weekday() in days
    return clock < end and (now.weekday() - 1) % 7 in days


def describe(schedule: Optional[Dict[str, Any]], lang: str = "tr") -> str:
    """'22:00–06:00 · Hafta içi' (or '· Weekdays' in English) for the rule list; '' for a rule that always runs."""
    if not has_window(schedule):
        return ""
    lang = "en" if lang == "en" else "tr"
    words = _WORDS[lang]
    days: List[int] = schedule.get("days") or ALL_DAYS
    if days == ALL_DAYS:
        which = words["every"]
    elif days == [0, 1, 2, 3, 4]:
        which = words["weekdays"]
    elif days == [5, 6]:
        which = words["weekend"]
    else:
        which = ", ".join(_DAY_NAMES[lang][day] for day in days)
    hours = words["all_day"] if schedule["start"] == schedule["end"] else f"{schedule['start']}–{schedule['end']}"
    return f"{hours} · {which}"
