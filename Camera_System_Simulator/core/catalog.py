"""
Camera System Simulator - Video Sets Catalog & Camera Metadata
Provides hyper-realistic metadata for all surveillance sets (set_1 through set_11),
including enterprise facility locations, IP addresses, RTSP stream paths,
resolutions, framerates, and synchronization lengths.
"""

import os
import json
import subprocess
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_SETS_DIR = os.path.join(BASE_DIR, "video_sets")

# Realistic enterprise location naming templates for multi-camera facility sets
SET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "set_1": {
        "title": "Corporate HQ - Main Facility & Perimeter",
        "description": "5-channel synchronized 720p HD surveillance covering main reception, primary entrance gate, east corridor, emergency stairwells, and secure loading bay.",
        "location": "Sector 1 - North Administrative Wing",
        "camera_names": [
            "CAM 01 - Main Entrance Gate (North)",
            "CAM 02 - Reception Lobby & Turnstiles",
            "CAM 03 - Ground Floor East Corridor",
            "CAM 04 - Emergency Exit & Stairwell B",
            "CAM 05 - Loading Bay & Secure Perimeter"
        ],
        "zone_tags": ["Perimeter", "Reception", "Hallway", "Fire Exit", "Logistics"]
    },
    "set_2": {
        "title": "Data Center & Research Complex",
        "description": "5-channel synchronized 720p HD surveillance monitoring server farm perimeter, clean room access, executive suites, central atrium, and staff breakout area.",
        "location": "Sector 2 - R&D & Server Vault",
        "camera_names": [
            "CAM 01 - Perimeter Fence West",
            "CAM 02 - Server Room Vault Door",
            "CAM 03 - 2nd Floor Executive Suite",
            "CAM 04 - Central Atrium Glasswalk",
            "CAM 05 - Cafeteria & Staff Breakroom"
        ],
        "zone_tags": ["Perimeter", "Vault", "Executive", "Atrium", "Breakroom"]
    },
    "set_3": {
        "title": "Logistics Hub & Freight Terminal",
        "description": "5-channel synchronized 720p HD surveillance overseeing north freight corridor, secure dispatch center, logistics dock, elevator bank, and rooftop access.",
        "location": "Sector 3 - Logistics & Freight Terminal",
        "camera_names": [
            "CAM 01 - North Freight Corridor",
            "CAM 02 - Secure Dispatch Center",
            "CAM 03 - Logistics Dock Level 2",
            "CAM 04 - High-Speed Elevator Lobby",
            "CAM 05 - Rooftop HVAC & Access Point"
        ],
        "zone_tags": ["Freight", "Dispatch", "Dock", "Elevators", "Rooftop"]
    },
    "set_4": {
        "title": "High-Security Compound & Parking Deck",
        "description": "5-channel extended synchronized 720p HD coverage for main checkpoint, visitor parking deck, east wing stairwell, classified archives, and perimeter alley.",
        "location": "Sector 4 - South Perimeter & Archive Facility",
        "camera_names": [
            "CAM 01 - Compound Checkpoint Alpha",
            "CAM 02 - Underground Parking Deck P1",
            "CAM 03 - East Wing Reinforced Stairway",
            "CAM 04 - Classified Archive 102",
            "CAM 05 - South Alley Security Perimeter"
        ],
        "zone_tags": ["Checkpoint", "Parking", "Stairway", "Archives", "Perimeter"]
    },
    "set_5": {
        "title": "Industrial Processing Facility A",
        "description": "6-channel synchronized surveillance covering raw materials entrance, processing line A, packaging corridor, supervisor office, storage yard, and back gate.",
        "location": "Industrial Facility A - Production Floor",
        "camera_names": [
            "CAM 01 - Raw Materials Inbound Gate",
            "CAM 02 - Assembly Line Primary Corridor",
            "CAM 03 - Secondary Packaging Bay",
            "CAM 04 - Shift Supervisor Control Room",
            "CAM 05 - External Materials Storage Yard",
            "CAM 06 - Auxiliary Gate & Fence Line"
        ],
        "zone_tags": ["Inbound", "Production", "Packaging", "Control", "Yard", "Gate"]
    },
    "set_6": {
        "title": "Industrial Processing Facility B",
        "description": "6-channel synchronized monitoring for automated assembly hall, quality inspection station, maintenance bay, logistics transit, perimeter patrol, and loading dock.",
        "location": "Industrial Facility B - Automated Section",
        "camera_names": [
            "CAM 01 - Automated Cell Ingress",
            "CAM 02 - Quality Assurance Line",
            "CAM 03 - Heavy Maintenance Workshop",
            "CAM 04 - Internal Transit Corridor",
            "CAM 05 - West Storage Warehouse",
            "CAM 06 - South Loading Dock Bay 3"
        ],
        "zone_tags": ["Robotics", "QA", "Workshop", "Transit", "Storage", "Dock"]
    },
    "set_7": {
        "title": "Chemical Processing & Utility Station",
        "description": "6-channel synchronized surveillance over chemical staging zone, mixing room perimeter, emergency eyewash stations, electrical switchgear room, yard, and perimeter fence.",
        "location": "Chemical & Utilities Complex - Tier 1",
        "camera_names": [
            "CAM 01 - Staging Area Alpha",
            "CAM 02 - Containment Zone Corridor",
            "CAM 03 - High-Voltage Switchgear Room",
            "CAM 04 - Environmental Scrubber Station",
            "CAM 05 - Northern Hazmat Enclosure",
            "CAM 06 - Boundary Fence Camera 7"
        ],
        "zone_tags": ["Hazmat", "Containment", "Power", "Scrubber", "Enclosure", "Fence"]
    },
    "set_8": {
        "title": "Secure Warehouse & Distribution Center",
        "description": "6-channel synchronized coverage over high-bay racking aisle 1, picking conveyor, forklift transit lane, shipping office, outdoor container yard, and gatehouse.",
        "location": "Distribution Center Central",
        "camera_names": [
            "CAM 01 - High-Bay Racking Aisle 1-4",
            "CAM 02 - High-Speed Picking Conveyor",
            "CAM 03 - Forklift Intersection Charlie",
            "CAM 04 - Shipping & Customs Office",
            "CAM 05 - Container Marshalling Yard",
            "CAM 06 - Perimeter Gatehouse Echo"
        ],
        "zone_tags": ["Aisles", "Conveyor", "Traffic", "Customs", "Containers", "Gate"]
    },
    "set_9": {
        "title": "Municipal Water & Pumping Station",
        "description": "6-channel synchronized telemetry monitoring filtration gallery, high-pressure pump room, chemical dosing room, monitoring lab, intake reservoir, and access gate.",
        "location": "Municipal Utility Zone 4",
        "camera_names": [
            "CAM 01 - Primary Filtration Hall",
            "CAM 02 - Turbine & Pump Gallery",
            "CAM 03 - Dosing Chemical Storage",
            "CAM 04 - SCADA Operations Lab",
            "CAM 05 - Intake Basin Perimeter",
            "CAM 06 - Restricted Site Entrance"
        ],
        "zone_tags": ["Filtration", "Pumps", "Chemicals", "SCADA", "Basin", "Entrance"]
    },
    "set_10": {
        "title": "Metro Transit Substation & Depot",
        "description": "6-channel synchronized cameras for rail maintenance shed, catenary line inspection, passenger access corridor, ticketing concourse, signaling room, and track switch yard.",
        "location": "Transit Terminal & Maintenance Depot",
        "camera_names": [
            "CAM 01 - Rolling Stock Service Bay",
            "CAM 02 - Traction Power Substation",
            "CAM 03 - Platform Passenger Ingress",
            "CAM 04 - Central Concourse & Turnstiles",
            "CAM 05 - Rail Signaling Relay Room",
            "CAM 06 - Switchyard Perimeter Gate"
        ],
        "zone_tags": ["Maintenance", "Traction", "Platform", "Concourse", "Signaling", "Switchyard"]
    },
    "set_11": {
        "title": "Government Administrative Archive Complex",
        "description": "6-channel synchronized surveillance across document vault entrance, digitized scanning lab, public reading room, secure corridors, staff entrance, and courtyard.",
        "location": "Civic Center - Records & Archives",
        "camera_names": [
            "CAM 01 - Document Vault Steel Ingress",
            "CAM 02 - Scanning & Preservation Lab",
            "CAM 03 - Public Records Reading Hall",
            "CAM 04 - Executive Archives Corridor",
            "CAM 05 - Employee Badge Turnstile",
            "CAM 06 - Exterior Courtyard & Flagpole"
        ],
        "zone_tags": ["Vault", "Lab", "Reading Hall", "Archives", "Staff Gate", "Courtyard"]
    }
}


def build_catalog() -> Dict[str, Any]:
    """Scans video_sets directory and compiles complete metadata for all sets."""
    sets = sorted(
        [d for d in os.listdir(VIDEO_SETS_DIR) if os.path.isdir(os.path.join(VIDEO_SETS_DIR, d))],
        key=lambda x: int(x.replace("set_", "")) if x.replace("set_", "").isdigit() else x
    )

    catalog = {}
    for set_id in sets:
        set_path = os.path.join(VIDEO_SETS_DIR, set_id)
        # Collect unique file stems (e.g. video1_1), preferring .mp4 over .avi
        all_files = os.listdir(set_path)
        stems = sorted(
            list(set(os.path.splitext(f)[0] for f in all_files if f.endswith((".avi", ".mp4")))),
            key=lambda x: [int(c) if c.isdigit() else c for c in x.replace("video", "").split("_")]
        )
        files = []
        for s in stems:
            mp4_cand = f"{s}.mp4"
            avi_cand = f"{s}.avi"
            if mp4_cand in all_files:
                files.append(mp4_cand)
            elif avi_cand in all_files:
                files.append(avi_cand)

        cfg = SET_CONFIGS.get(set_id, {
            "title": f"Surveillance Set {set_id.replace('set_', '')}",
            "description": f"{len(files)}-channel synchronized camera set.",
            "location": f"Sector {set_id.replace('set_', '')}",
            "camera_names": [f"CAM 0{i+1} - Zone {i+1}" for i in range(len(files))],
            "zone_tags": [f"Zone {i+1}" for i in range(len(files))]
        })

        cameras = []
        min_duration = 999999.0

        for idx, fname in enumerate(files):
            fpath = os.path.join(set_path, fname)
            cam_num = idx + 1
            cam_id = f"cam{cam_num}"

            # Probe media format
            try:
                cmd = [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,r_frame_rate,duration,codec_name",
                    "-show_entries", "format=duration,size",
                    "-of", "json", fpath
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                probe_data = json.loads(res.stdout)
                stream_info = probe_data.get("streams", [{}])[0]
                fmt_info = probe_data.get("format", {})

                width = int(stream_info.get("width", 1280))
                height = int(stream_info.get("height", 720))
                codec = stream_info.get("codec_name", "mpeg4")
                fps_str = stream_info.get("r_frame_rate", "30/1")
                fps = round(eval(fps_str), 1) if "/" in fps_str else float(fps_str)
                dur = float(fmt_info.get("duration", stream_info.get("duration", 60.0)))
                size_bytes = int(fmt_info.get("size", os.path.getsize(fpath)))
            except Exception:
                width, height, fps, dur, codec, size_bytes = 1280, 720, 30.0, 60.0, "mpeg4", 20000000

            if dur < min_duration:
                min_duration = dur

            cam_name = cfg["camera_names"][idx] if idx < len(cfg["camera_names"]) else f"CAM 0{cam_num} - Channel {cam_num}"
            zone_tag = cfg["zone_tags"][idx] if idx < len(cfg["zone_tags"]) else f"Zone {cam_num}"

            # Realistic IP / MAC assignment
            ip_suffix = 100 + cam_num
            mac_suffix = f"{cam_num:02X}"

            cameras.append({
                "id": cam_id,
                "channel": cam_num,
                "name": cam_name,
                "location": f"{cfg['location']} / {zone_tag}",
                "zone": zone_tag,
                "filename": fname,
                "filepath": fpath,
                "width": width,
                "height": height,
                "resolution": f"{width}x{height}",
                "resolution_label": "1080p Full HD" if height >= 1080 else ("720p HD" if height >= 720 else "480p D1"),
                "fps": fps,
                "codec": codec,
                "stream_codec": "H.264 (AVC)",
                "duration": round(dur, 2),
                "filesize_mb": round(size_bytes / (1024 * 1024), 2),
                "ip_address": f"192.168.1.{ip_suffix}",
                "mac_address": f"44:E1:37:A9:04:{mac_suffix}",
                "firmware": "v5.9.14-build260920",
                "rtsp_url": f"rtsp://127.0.0.1:8554/{cam_id}",
                "webrtc_whep_url": f"http://127.0.0.1:8889/{cam_id}/whep",
                "hls_url": f"http://127.0.0.1:8888/{cam_id}/index.m3u8",
                "mjpeg_url": f"/api/cameras/{cam_id}/mjpeg",
                "snapshot_url": f"/api/cameras/{cam_id}/snapshot",
                "status": "ONLINE",
                "night_vision": "AUTO",
                "audio_supported": False
            })

        catalog[set_id] = {
            "id": set_id,
            "title": cfg["title"],
            "description": cfg["description"],
            "location": cfg["location"],
            "camera_count": len(cameras),
            "resolution": cameras[0]["resolution"] if cameras else "Unknown",
            "resolution_label": cameras[0]["resolution_label"] if cameras else "HD",
            "sync_duration": round(min_duration, 2),
            "cameras": cameras
        }

    return catalog


# Singleton catalog instance cached in memory
CATALOG = build_catalog()


def get_catalog() -> Dict[str, Any]:
    return CATALOG


def get_set_metadata(set_id: str) -> Dict[str, Any]:
    return CATALOG.get(set_id, CATALOG.get("set_1"))
