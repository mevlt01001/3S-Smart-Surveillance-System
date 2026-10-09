"""
Rules & Spatial Polygon Zones Management Service
Manages user-defined surveillance rules (camera-wise or system-wise) with
interactive polygon geometries and natural-language descriptions.
Persists rules to rules_db.json.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Dict, List, Optional, Any

from .paths import data_path, atomic_write_json

logger = logging.getLogger("aegis.rules")

RULES_DB_PATH = data_path("rules_db.json")


class RulesService:
    def __init__(self):
        self.rules: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._last_mtime: float = 0.0
        self.load_from_disk()
        self._remember_mtime()

    def _remember_mtime(self):
        try:
            self._last_mtime = os.path.getmtime(RULES_DB_PATH)
        except OSError:
            self._last_mtime = 0.0

    def load_from_disk(self):
        """Loads rules from JSON file and cleans up redundant legacy polygon fields."""
        if os.path.exists(RULES_DB_PATH):
            try:
                with open(RULES_DB_PATH, "r", encoding="utf-8") as f:
                    self.rules = json.load(f)
                
                # Cleanup legacy redundant fields
                cleaned = False
                for r in self.rules.values():
                    if "polygons" in r:
                        del r["polygons"]
                        cleaned = True
                    if "polygon" in r:
                        del r["polygon"]
                        cleaned = True
                if cleaned:
                    self.save_to_disk()
            except Exception as e:
                # Keep the rules already in memory: wiping them here would let the next save
                # overwrite a (temporarily) unreadable database with an empty one.
                logger.warning(f"Error loading rules from {RULES_DB_PATH}: {e}")
        else:
            self.rules = {}

    def save_to_disk(self):
        """Persists rules to JSON file."""
        with self._lock:
            try:
                atomic_write_json(RULES_DB_PATH, self.rules)
                # Our own write must not be mistaken for an external edit (avoids a full re-parse)
                self._remember_mtime()
            except Exception as e:
                logger.warning(f"Error saving rules to {RULES_DB_PATH}: {e}")

    def get_all(self, camera_id: Optional[str] = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """Returns all rules, optionally filtered by camera_id and/or enabled status."""
        try:
            mtime = os.path.getmtime(RULES_DB_PATH)
            if mtime != self._last_mtime:
                with self._lock:
                    self.load_from_disk()
                    self._last_mtime = mtime
        except OSError:
            pass

        with self._lock:
            rules_list = list(self.rules.values())

        # Filter by enabled status when requested
        if enabled_only:
            rules_list = [r for r in rules_list if r.get("enabled", True)]

        if camera_id:
            return [r for r in rules_list if r.get("scope") == "system" or r.get("camera_id") == camera_id]
        return sorted(rules_list, key=lambda r: r.get("created_at", 0), reverse=True)

    def get_by_id(self, rule_id: str) -> Optional[Dict[str, Any]]:
        return self.rules.get(rule_id)

    def create_rule(
        self,
        title: str,
        scope: str = "camera",
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        severity: str = "warning",
        description: str = "",
        zones: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Creates a new rule with per-zone rules (single source of truth in zones)."""
        rule_id = f"rule_{uuid.uuid4().hex[:10]}"
        now = time.time()

        zones_list = zones or []

        if not description.strip() and zones_list:
            zone_desc_parts = [f"{z.get('name', 'Bölge')}: {z.get('description', '')}" for z in zones_list if z.get("description")]
            description = " | ".join(zone_desc_parts)

        rule_data = {
            "id": rule_id,
            "title": title.strip() or "İsimsiz Kural",
            "scope": scope if scope in ["camera", "system"] else "camera",
            "camera_id": camera_id if scope == "camera" else None,
            "camera_name": camera_name if scope == "camera" else "Tüm kameralar",
            "severity": severity if severity in ["critical", "warning", "info"] else "warning",
            "description": description.strip(),
            "zones": zones_list,
            "actions": actions or ["alert_screen", "snapshot"],
            "enabled": True,
            "created_at": now,
            "updated_at": now
        }

        self.rules[rule_id] = rule_data
        self.save_to_disk()
        return rule_data

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates rule fields."""
        rule = self.rules.get(rule_id)
        if not rule:
            return None

        for k, v in updates.items():
            if k in ["title", "severity", "description", "zones", "actions", "enabled", "camera_id", "camera_name", "scope", "assignee", "escalation"]:
                rule[k] = v

        rule["updated_at"] = time.time()
        self.save_to_disk()
        return rule

    def delete_rules_for_camera(self, camera_id: str) -> int:
        """Removes camera-scoped rules of a deleted camera so they do not linger as orphans."""
        with self._lock:
            doomed = [rid for rid, r in self.rules.items()
                      if r.get("scope") != "system" and r.get("camera_id") == camera_id]
            for rid in doomed:
                del self.rules[rid]
            if doomed:
                self.save_to_disk()
            return len(doomed)

    def delete_rule(self, rule_id: str) -> bool:
        """Deletes a rule by ID."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            self.save_to_disk()
            return True
        return False


# Global singleton instance
rules_service = RulesService()
