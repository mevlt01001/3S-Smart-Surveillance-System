"""
PlaybackEngine: Real Synchronized NVR Playback Engine
Operates directly on the 5-frame MP4 micro-segments saved in local storage.
Provides synchronized time-to-segment mapping across all active cameras.
"""

import os
from typing import Dict, List, Any, Optional
from .catalog import get_set_metadata
from .storage import storage_manager, RECORDINGS_DIR


class PlaybackEngine:
    def __init__(self):
        pass

    def get_camera_recording_source(self, cam_id: str, set_id: str) -> Optional[str]:
        """Returns the local H.264 MP4 video file path for seamless synchronized playback."""
        set_meta = get_set_metadata(set_id)
        cam = next((c for c in set_meta.get("cameras", []) if c["id"] == cam_id), None)
        if not cam:
            return None
        filepath = cam["filepath"]
        if filepath.endswith(".avi"):
            mp4_path = filepath[:-4] + ".mp4"
            if os.path.isfile(mp4_path):
                return mp4_path
        return filepath

    def get_timeline_metadata(self, set_id: str) -> Dict[str, Any]:
        """
        Calculates the timeline of genuine recorded segments physically present
        in the local NVR storage ring buffer.
        """
        rec_data = storage_manager.get_recorded_timeline()
        set_meta = get_set_metadata(set_id)
        cameras = set_meta.get("cameras", [])

        cams_data = rec_data.get("cameras", {})
        retention_sec = rec_data.get("retention_seconds", 0.0)

        timeline_channels = []
        for cam in cameras:
            cid = cam["id"]
            c_segs = cams_data.get(cid, [])
            count = len(c_segs)

            # Continuous green block representing actual recorded window
            blocks = []
            if count > 0:
                # 5 frames per segment at ~30fps is ~0.166s
                approx_dur = round(count * 0.166, 1)
                blocks.append({
                    "type": "recorded",
                    "start": 0.0,
                    "end": approx_dur,
                    "color": "#10b981", # Emerald green
                    "label": f"Local Disk Recording ({count} segments / 5-frames each)"
                })

            timeline_channels.append({
                "camera_id": cid,
                "camera_name": cam["name"],
                "channel": cam["channel"],
                "segment_count": count,
                "segments": blocks
            })

        return {
            "set_id": set_id,
            "duration": max(retention_sec, 1.0),
            "max_storage_mb": rec_data.get("max_mb", 200.0),
            "used_storage_mb": rec_data.get("used_mb", 0.0),
            "timeline": timeline_channels
        }

    def get_sync_segment_for_offset(self, offset_sec: float, set_id: str) -> Dict[str, Any]:
        """
        Given a scrubbed time offset in seconds from the start of available recorded footage,
        returns the matching 5-frame MP4 segment URL for each camera.
        """
        set_meta = get_set_metadata(set_id)
        cameras = set_meta.get("cameras", [])

        # Target index based on ~0.166 seconds per 5-frame segment
        target_idx = max(0, int(offset_sec / 0.166))

        results = {}
        for cam in cameras:
            cid = cam["id"]
            cam_dir = os.path.join(RECORDINGS_DIR, cid)
            if os.path.isdir(cam_dir):
                files = sorted([f for f in os.listdir(cam_dir) if f.endswith(".mp4")])
                if files:
                    # Clamp index within available segments
                    idx = min(target_idx, len(files) - 1)
                    seg_file = files[idx]
                    results[cid] = {
                        "segment_file": seg_file,
                        "url": f"/api/storage/segment/{cid}/{seg_file}",
                        "index": idx,
                        "total_segments": len(files)
                    }
        return results
