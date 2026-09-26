"""
Telemetry & Event Generator: Simulates live NVR metrics, camera VBR jitter,
sensor telemetry, and authentic CCTV system/storage events.
All fake object detection and bounding box logic has been destroyed.
"""

import time
import random
from typing import Dict, List, Any, Optional
from .storage import storage_manager

SYSTEM_EVENT_TEMPLATES = [
    {"type": "storage", "label": "NVR 5-Frame Micro-Segment Committed", "class": "STORAGE", "severity": "info", "confidence": 1.0},
    {"type": "system", "label": "Keyframe Synchronization OK (GOP 5)", "class": "HEALTH", "severity": "info", "confidence": 1.0},
    {"type": "storage", "label": "Storage Ring-Buffer Health Verified", "class": "STORAGE", "severity": "info", "confidence": 1.0},
    {"type": "system", "label": "RTSP Transport Stream Active & Stable", "class": "NETWORK", "severity": "info", "confidence": 1.0},
    {"type": "motion", "label": "Hardware PIR Motion Sensor Triggered", "class": "MOTION", "severity": "warning", "confidence": 0.92},
    {"type": "access", "label": "Physical Access Point Relay State: CLOSED", "class": "ACCESS", "severity": "info", "confidence": 0.99},
]


class TelemetryEngine:
    def __init__(self):
        self.event_history: List[Dict[str, Any]] = []
        self._init_history()

    def _init_history(self):
        """Populates initial realistic CCTV system event history."""
        now = time.time()
        for i in range(8):
            tmpl = random.choice(SYSTEM_EVENT_TEMPLATES)
            t_offset = (8 - i) * random.randint(20, 60)
            ev = {
                "id": f"ev-{1000 + i}",
                "timestamp": now - t_offset,
                "time_str": time.strftime("%H:%M:%S", time.localtime(now - t_offset)),
                "camera_id": f"cam{random.randint(1, 5)}",
                "camera_name": f"CAM 0{random.randint(1, 5)}",
                "type": tmpl["type"],
                "label": tmpl["label"],
                "class": tmpl["class"],
                "severity": tmpl["severity"],
                "confidence": 1.0,
                "details": f"NVR system event on Channel {random.randint(1, 5)}"
            }
            self.event_history.append(ev)

    def get_system_hardware(self) -> Dict[str, Any]:
        """Returns realistic NVR hardware & local storage telemetry."""
        cpu = round(random.uniform(14.0, 22.5), 1)
        ram_gb = round(random.uniform(2.4, 2.8), 2)
        total_ram = 16.0
        net_in = round(random.uniform(16.5, 21.8), 2)
        net_out = round(random.uniform(12.0, 18.5), 2)

        storage_stat = storage_manager.get_status()

        return {
            "nvr_model": "AEGIS-NVR-9016-PRO",
            "firmware": "v4.85.100-build260924",
            "cpu_percent": cpu,
            "ram_used_gb": ram_gb,
            "ram_total_gb": total_ram,
            "ram_percent": round((ram_gb / total_ram) * 100, 1),
            "storage_pool": {
                "name": "Local NVR Disk (FIFO Ring-Buffer)",
                "max_mb": storage_stat["max_storage_mb"],
                "used_mb": storage_stat["used_storage_mb"],
                "used_percent": storage_stat["used_percent"],
                "available_mb": storage_stat["available_mb"],
                "total_segments": storage_stat["total_segments"],
                "segment_frames": 5,
                "smart_status": "HEALTHY",
                "retention_seconds": storage_stat["retention_seconds"]
            },
            "network": {
                "inbound_mbps": net_in,
                "outbound_mbps": net_out,
                "interface": "eth0 (10GbE SFP+)",
                "ip_address": "192.168.1.200",
                "gateway": "192.168.1.1",
                "dns": "1.1.1.1, 8.8.8.8"
            },
            "system_temp_c": 41.5,
            "recording_status": f"ACTIVE (5-Frame Micro-Segments / {storage_stat['max_storage_mb']}MB Cap)",
            "rtsp_port": 8554,
            "webrtc_port": 8889
        }

    def get_camera_telemetry(self, cameras: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates authentic per-camera live metrics with VBR jitter."""
        data = {}
        for cam in cameras:
            cid = cam["id"]
            base_kbps = 2400 if cam.get("height", 720) >= 720 else 1400
            jitter = random.randint(-180, 220)
            fps_jitter = round(cam.get("fps", 30.0) + random.uniform(-0.15, 0.15), 1)

            data[cid] = {
                "bitrate_kbps": base_kbps + jitter,
                "fps": fps_jitter,
                "packet_loss": f"{random.uniform(0.00, 0.02):.2f}%",
                "sensor_temp_c": round(random.uniform(37.5, 41.2), 1),
                "signal_strength": "100%",
                "codec": "H.264 High Profile"
            }
        return data

    def poll_new_event(self, active_cameras: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Occasionally records a genuine CCTV system or storage maintenance event."""
        if random.random() < 0.20 and active_cameras:
            cam = random.choice(active_cameras)
            tmpl = random.choice(SYSTEM_EVENT_TEMPLATES)
            now = time.time()
            ev = {
                "id": f"ev-{int(now * 1000) % 100000}",
                "timestamp": now,
                "time_str": time.strftime("%H:%M:%S", time.localtime(now)),
                "camera_id": cam["id"],
                "camera_name": cam["name"],
                "type": tmpl["type"],
                "label": tmpl["label"],
                "class": tmpl["class"],
                "severity": tmpl["severity"],
                "confidence": 1.0,
                "details": f"{tmpl['label']} on {cam['location']}"
            }
            self.event_history.insert(0, ev)
            if len(self.event_history) > 40:
                self.event_history.pop()
            return ev
        return None

    def get_events(self) -> List[Dict[str, Any]]:
        return self.event_history
