"""
Rules & Spatial Polygon Zones Management Service
Manages user-defined surveillance rules (camera-wise or system-wise) with
interactive polygon geometries and natural-language descriptions.
Persists rules to rules_db.json.
"""

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Any

RULES_DB_PATH = os.path.join(os.path.dirname(__file__), "rules_db.json")


class RulesService:
    def __init__(self):
        self.rules: Dict[str, Dict[str, Any]] = {}
        self.load_from_disk()

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
                    if "assignee" not in r:
                        r["assignee"] = {
                            "name": "Nöbetçi Güvenlik / Saha Şefi",
                            "role": "Saha Sorumlusu",
                            "phone": "Dahili 104"
                        }
                        cleaned = True
                    if "escalation" not in r:
                        r["escalation"] = {
                            "supervisor_name": "İSG Müdürü",
                            "supervisor_role": "Tesis Direktörü",
                            "timeout_minutes": 5
                        }
                        cleaned = True
                if cleaned:
                    self.save_to_disk()
            except Exception as e:
                print(f"[RulesService] Error loading rules from {RULES_DB_PATH}: {e}")
                self.rules = {}
        else:
            self.rules = {}

    def save_to_disk(self):
        """Persists rules to JSON file."""
        try:
            with open(RULES_DB_PATH, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[RulesService] Error saving rules to {RULES_DB_PATH}: {e}")

    def get_all(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all rules, optionally filtered by camera_id."""
        rules_list = list(self.rules.values())
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
        assignee: Optional[Dict[str, Any]] = None,
        escalation: Optional[Dict[str, Any]] = None,
        **kwargs
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
            "camera_name": camera_name if scope == "camera" else "Tüm Sistem (Global)",
            "severity": severity if severity in ["critical", "warning", "info"] else "warning",
            "description": description.strip(),
            "zones": zones_list,
            "actions": actions or ["alert_screen", "snapshot"],
            "assignee": assignee or {
                "name": "Nöbetçi Güvenlik / Saha Şefi",
                "role": "Saha Sorumlusu",
                "phone": "Dahili 104"
            },
            "escalation": escalation or {
                "supervisor_name": "İSG Müdürü",
                "supervisor_role": "Tesis Direktörü",
                "timeout_minutes": 5
            },
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

    def delete_rule(self, rule_id: str) -> bool:
        """Deletes a rule by ID."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            self.save_to_disk()
            return True
        return False
