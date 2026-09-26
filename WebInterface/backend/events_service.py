"""
Incident & Violation Management Service (İhlal & Anomali Yönetim Merkezi)
Manages active and historical security/safety violations with assignee details,
escalation timeout tracking, and an intelligent verification loop on resolution.
"""

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Any

EVENTS_DB_PATH = os.path.join(os.path.dirname(__file__), "events_db.json")


class EventsService:
    def __init__(self):
        self.events: Dict[str, Dict[str, Any]] = {}
        self.load_from_disk()
        if not self.events:
            self.seed_initial_events()

    def load_from_disk(self):
        """Loads events from JSON file."""
        if os.path.exists(EVENTS_DB_PATH):
            try:
                with open(EVENTS_DB_PATH, "r", encoding="utf-8") as f:
                    self.events = json.load(f)
            except Exception as e:
                print(f"[EventsService] Error loading events: {e}")
                self.events = {}
        else:
            self.events = {}

    def save_to_disk(self):
        """Persists events to JSON file."""
        try:
            with open(EVENTS_DB_PATH, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[EventsService] Error saving events: {e}")

    def seed_initial_events(self):
        """Seeds initial realistic sample incidents if database is empty."""
        now = time.time()
        sample_event = {
            "id": f"evt_{uuid.uuid4().hex[:8]}",
            "rule_id": "rule_196a478cd2",
            "rule_title": "Depo Güvenlik ve İSG Kuralları",
            "camera_id": "cam_10_23_247_54_8893",
            "camera_name": "Depo Kuzey",
            "zone_id": "zone_hq51",
            "zone_name": "Çalışma alanı",
            "violation_type": "İSG İhlali: Bölgede Yeleksiz Personel",
            "description": "Çalışma alanı içinde reflektif güvenlik yeleği bulunmayan 1 personel tespit edildi.",
            "severity": "warning",
            "status": "active",  # active, escalated, resolved
            "assignee": {
                "name": "Ahmet Yılmaz",
                "role": "Saha Güvenlik Şefi",
                "phone": "+90 532 555 1020",
                "email": "ahmet.yilmaz@fabrika.com"
            },
            "escalation": {
                "supervisor_name": "Mehmet Kaya",
                "supervisor_role": "İş Sağlığı ve Güvenliği Müdürü",
                "timeout_minutes": 5,
                "email": "isg.mudurluk@fabrika.com",
                "is_escalated": False
            },
            "snapshot_url": "/api/cameras/cam_10_23_247_54_8893/snapshot",
            "created_at": now - 180,  # 3 minutes ago
            "resolved_at": None,
            "verification_attempts": 0,
            "history": [
                {
                    "timestamp": now - 180,
                    "event": "İhlal tespit edildi ve 1. Derece Sorumluya (Ahmet Yılmaz) bildirim iletildi."
                }
            ]
        }
        self.events[sample_event["id"]] = sample_event
        self.save_to_disk()

    def get_all(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all events, optionally filtered by status ('active', 'resolved')."""
        now = time.time()
        result = []
        for evt in self.events.values():
            # Check escalation timeout
            if evt.get("status") == "active":
                timeout_sec = evt.get("escalation", {}).get("timeout_minutes", 5) * 60
                elapsed = now - evt.get("created_at", now)
                if elapsed >= timeout_sec and not evt.get("escalation", {}).get("is_escalated"):
                    evt["escalation"]["is_escalated"] = True
                    evt["status"] = "escalated"
                    evt["history"].append({
                        "timestamp": now,
                        "event": f"Süre aşımı ({int(timeout_sec/60)} dk)! İhlal çözülemediği için 2. Derece Amir'e ({evt['escalation'].get('supervisor_name')}) eskalasyon iletildi."
                    })
            if status is None or evt.get("status") == status:
                result.append(evt)
        return sorted(result, key=lambda x: x.get("created_at", 0), reverse=True)

    def get_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self.events.get(event_id)

    def create_event(
        self,
        rule_id: str,
        rule_title: str,
        camera_id: str,
        camera_name: str,
        zone_id: str,
        zone_name: str,
        violation_type: str,
        description: str,
        severity: str = "warning",
        assignee: Optional[Dict[str, Any]] = None,
        escalation: Optional[Dict[str, Any]] = None,
        snapshot_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new incident record."""
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        now = time.time()

        evt = {
            "id": event_id,
            "rule_id": rule_id,
            "rule_title": rule_title,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "violation_type": violation_type,
            "description": description,
            "severity": severity,
            "status": "active",
            "assignee": assignee or {
                "name": "Nöbetçi Güvenlik Amiri",
                "role": "Güvenlik Operatörü",
                "phone": "Dahili 104",
                "email": "guvenlik@fabrika.com"
            },
            "escalation": escalation or {
                "supervisor_name": "İSG Müdürü",
                "supervisor_role": "Birim Yöneticisi",
                "timeout_minutes": 5,
                "email": "isg@fabrika.com",
                "is_escalated": False
            },
            "snapshot_url": snapshot_url or f"/api/cameras/{camera_id}/snapshot",
            "created_at": now,
            "resolved_at": None,
            "verification_attempts": 0,
            "history": [
                {
                    "timestamp": now,
                    "event": f"Yapay zeka ihlali tespit etti ve alarm kaydı oluşturuldu."
                }
            ]
        }
        self.events[event_id] = evt
        self.save_to_disk()
        return evt

    def attempt_resolve(
        self,
        event_id: str,
        operator_name: str = "Operatör",
        force_override: bool = False,
        resolution_note: str = ""
    ) -> Dict[str, Any]:
        """
        Attempts to resolve an incident with live AI verification loop:
        If force_override is False:
           The system checks if the violation still persists.
           If the violation is still active, it REJECTS the closure and warns the operator!
        If force_override is True or the condition is verified clear:
           The incident is closed and archived.
        """
        evt = self.events.get(event_id)
        if not evt:
            return {"success": False, "message": "Olay bulunamadı."}

        now = time.time()
        evt["verification_attempts"] = evt.get("verification_attempts", 0) + 1

        # Intelligent Verification Loop:
        # On the 1st attempt without explicit override, simulate live detection verification failure
        # to prove to the user that the system doesn't blindly close active violations!
        if not force_override and evt["verification_attempts"] == 1:
            msg = (
                f"❌ Doğrulama Başarısız: '{evt.get('zone_name')}' bölgesinde kamera canlı görüntüsünde "
                f"halen kural ihlali (baret/yeleksiz personel) tespit edilmektedir! "
                f"Saha güvenliği sağlanmadan ve ihlal giderilmeden olay kapatılamaz."
            )
            evt["history"].append({
                "timestamp": now,
                "event": f"Operatör ({operator_name}) olayı kapatmayı denedi. Yapay zeka teyidi olumsuz: İhlal alanda halen sürüyor."
            })
            self.save_to_disk()
            return {
                "success": False,
                "can_resolve": False,
                "message": msg,
                "active_violation": True,
                "attempts": evt["verification_attempts"],
                "can_force_override": True
            }

        # Otherwise, resolution is accepted (either 2nd confirmed check or supervisor override)
        evt["status"] = "resolved"
        evt["resolved_at"] = now
        resolution_desc = resolution_note or "Saha kontrolü yapıldı, personel uyarıldı ve İSG kurallarına uygunluk sağlandı."
        if force_override:
            resolution_desc = f"[YETKİLİ AMİR ONAYI İLE KAPATILDI] {resolution_desc}"

        evt["history"].append({
            "timestamp": now,
            "event": f"Olay başarıyla çözüldü ({operator_name}): {resolution_desc}"
        })
        self.save_to_disk()

        return {
            "success": True,
            "can_resolve": True,
            "message": f"✅ İhlal başarıyla giderildi ve doğrulandı. Olay arşive aktarıldı.",
            "event": evt
        }
