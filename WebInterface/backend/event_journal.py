"""
Event journal: the persistent list of recorded incidents, newest first.

Every change is saved to disk and announced on the live event feed, so callers only state
what happened. Entries handed out are copies; worker threads keep changing the originals.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from . import evidence_store
from .event_stream import event_stream
from .paths import atomic_write_json, data_path

logger = logging.getLogger("aegis.journal")

JOURNAL_PATH = data_path("anomaly_journal.json")
OPERATOR_LABELS = ("correct", "false_positive", "unlabeled")

Entry = Dict[str, Any]


def is_rule_violation(entry: Entry) -> bool:
    return str(entry.get("id", "")).startswith("rule_")


class EventJournal:
    def __init__(self):
        self._entries: List[Entry] = []
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if os.path.exists(JOURNAL_PATH):
            try:
                with open(JOURNAL_PATH, "r", encoding="utf-8") as file:
                    data = json.load(file)
                self._entries = data if isinstance(data, list) else []
            except (OSError, ValueError) as exc:
                logger.error("Journal could not be read (%s); starting with an empty journal.", exc)

        # Entries interrupted by a restart must not stay "ongoing" / "generating" forever
        repaired = False
        for entry in self._entries:
            if entry.get("is_ongoing"):
                entry.update(is_ongoing=False, interrupted=True,
                             end_time_str=entry.get("peak_time_str") or entry.get("timestamp_str") or "")
                repaired = True
            if entry.get("ai_status") == "generating":
                entry["ai_status"] = "completed" if entry.get("ai_summary") else "interrupted"
                repaired = True
        if repaired:
            self._save()

    def _save(self) -> None:
        with self._lock:
            try:
                atomic_write_json(JOURNAL_PATH, self._entries)
            except OSError as exc:
                logger.error("Journal could not be saved: %s", exc)

    # ---------------------------------------------------------------- writing
    def add(self, entry: Entry, capacity: int) -> None:
        """Records a new event. Events beyond `capacity` are dropped together with their evidence files."""
        with self._lock:
            self._entries.insert(0, entry)
            dropped, self._entries = self._entries[capacity:], self._entries[:capacity]
            self._save()
        for old in dropped:
            evidence_store.delete_files_of(old)
        event_stream.publish({"type": "new_anomaly", "entry": entry})

    def update(self, entry_id: str, **changes: Any) -> Optional[Entry]:
        """Changes fields of an event. Returns the updated event, or None when it no longer exists."""
        with self._lock:
            entry = next((item for item in self._entries if item.get("id") == entry_id), None)
            if entry is None:
                return None
            entry.update(changes)
            self._save()
            snapshot = dict(entry)
        event_stream.publish({"type": "update_anomaly", "entry": snapshot})
        return snapshot

    def set_label(self, entry_id: str, label: str, notes: str = "", operator_name: str = "Operatör") -> Optional[Entry]:
        """Stores the operator's verdict. Raises ValueError for an unknown label."""
        if label not in OPERATOR_LABELS:
            raise ValueError(f"Geçersiz etiket: {label}")
        return self.update(
            entry_id,
            operator_label=label,
            operator_notes=notes or "",
            operator_name=operator_name,
            operator_labeled_at=time.time(),
        )

    def expire_clips(self, clip_names: List[str]) -> None:
        """Marks events whose clip was deleted to free disk space."""
        if not clip_names:
            return
        with self._lock:
            for entry in self._entries:
                if entry.get("clip_url") and evidence_store.file_name(entry["clip_url"]) in clip_names:
                    entry.update(clip_url=None, clip_expired=True)
            self._save()

    def clear(self) -> List[Entry]:
        """Removes every event and returns them (the caller deletes their evidence)."""
        with self._lock:
            removed, self._entries = self._entries, []
            self._save()
        event_stream.publish({"type": "journal_cleared"})
        return removed

    # ---------------------------------------------------------------- reading
    def get(self, entry_id: str) -> Optional[Entry]:
        with self._lock:
            entry = next((item for item in self._entries if item.get("id") == entry_id), None)
            return dict(entry) if entry else None

    def list(self, camera_id: Optional[str] = None, tier: Optional[str] = None,
             operator_label: Optional[str] = None, limit: int = 250) -> List[Entry]:
        def matches(entry: Entry) -> bool:
            if camera_id and entry.get("camera_id") != camera_id:
                return False
            if tier and entry.get("tier") != tier:
                return False
            if operator_label and (entry.get("operator_label") or "unlabeled") != operator_label:
                return False
            return True

        with self._lock:
            return [dict(entry) for entry in self._entries if matches(entry)][:max(0, limit)]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            entries = list(self._entries)
        count = lambda test: sum(1 for entry in entries if test(entry))  # noqa: E731
        critical = count(lambda e: e.get("tier") == "critical")
        warning = count(lambda e: e.get("tier") == "warning")
        correct = count(lambda e: e.get("operator_label") == "correct")
        false_positive = count(lambda e: e.get("operator_label") == "false_positive")
        return {
            "total_events": len(entries),
            "critical_count": critical,
            "warning_count": warning,
            "normal_count": count(lambda e: e.get("tier") == "normal"),
            "rule_violation_count": count(is_rule_violation),
            "total_warnings": critical + warning,
            "correct_count": correct,
            "false_positive_count": false_positive,
            "unlabeled_count": len(entries) - correct - false_positive,
        }

    def referenced_files(self) -> Tuple[Set[str], Set[str]]:
        """Names of the clips and of the snapshots that events point to."""
        with self._lock:
            clips = {evidence_store.file_name(e["clip_url"]) for e in self._entries if e.get("clip_url")}
            snapshots = {evidence_store.file_name(e["snapshot_url"]) for e in self._entries if e.get("snapshot_url")}
        return clips, snapshots

    def __len__(self) -> int:
        return len(self._entries)


event_journal = EventJournal()
