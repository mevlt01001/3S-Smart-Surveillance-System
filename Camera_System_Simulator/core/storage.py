"""
StorageManager: Simulates CCTV/NVR Local Hard Drive Storage
Records 5-frame micro-segments from live streams, maintains a strict
FIFO ring-buffer quota (default 200 MB, adjustable from Web UI),
and indexes recorded segments for synchronized playback.
"""

import os
import glob
import time
import shutil
import logging
import threading
from typing import Dict, List, Optional, Any

logger = logging.getLogger("NVRStorage")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")


class StorageManager:
    def __init__(self, default_quota_mb: float = 200.0):
        self.max_storage_mb = default_quota_mb
        self.recordings_dir = RECORDINGS_DIR
        self.lock = threading.Lock()
        self.is_running = True
        self.start_time = time.time()

        os.makedirs(self.recordings_dir, exist_ok=True)

        # Start storage monitor thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def reset_storage_for_set(self, camera_ids: List[str]):
        """Initializes empty recording directories for active cameras."""
        with self.lock:
            # Clear old recordings to start fresh ring buffer for current set
            if os.path.exists(self.recordings_dir):
                shutil.rmtree(self.recordings_dir, ignore_errors=True)
            os.makedirs(self.recordings_dir, exist_ok=True)
            for cid in camera_ids:
                os.makedirs(os.path.join(self.recordings_dir, cid), exist_ok=True)
            self.start_time = time.time()
            logger.info(f"Initialized local NVR storage for {len(camera_ids)} cameras (Quota: {self.max_storage_mb} MB)")

    def get_current_storage_bytes(self) -> int:
        """Calculates total disk bytes used by all recorded segments."""
        total = 0
        if not os.path.exists(self.recordings_dir):
            return 0
        for root, _, files in os.walk(self.recordings_dir):
            for f in files:
                if f.endswith(".mp4"):
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        return total

    def get_current_storage_mb(self) -> float:
        return round(self.get_current_storage_bytes() / (1024 * 1024), 2)

    def set_max_storage_mb(self, mb: float) -> Dict[str, Any]:
        """Dynamically adjusts disk quota from Web UI and triggers immediate purge if needed."""
        with self.lock:
            self.max_storage_mb = max(10.0, float(mb))
            logger.info(f"Updated NVR Storage Quota to: {self.max_storage_mb} MB")
            self._purge_if_needed()
        return self.get_status()

    def _purge_if_needed(self):
        """Enforces FIFO ring buffer: purges oldest 5-frame segments when quota is exceeded."""
        current_mb = self.get_current_storage_mb()
        if current_mb <= self.max_storage_mb:
            return

        target_mb = self.max_storage_mb * 0.90 # Purge down to 90%
        logger.info(f"Storage quota exceeded: {current_mb} MB >= {self.max_storage_mb} MB. Purging oldest segments to {target_mb} MB...")

        # Gather all segment files across all cameras with timestamps
        all_segments = []
        for cam_dir in os.listdir(self.recordings_dir):
            cpath = os.path.join(self.recordings_dir, cam_dir)
            if os.path.isdir(cpath):
                for f in os.listdir(cpath):
                    if f.endswith(".mp4"):
                        fp = os.path.join(cpath, f)
                        try:
                            mtime = os.path.getmtime(fp)
                            size = os.path.getsize(fp)
                            all_segments.append((fp, mtime, size, cam_dir, f))
                        except OSError:
                            pass

        # Sort by modification time ascending (oldest first)
        all_segments.sort(key=lambda x: x[1])

        deleted_count = 0
        deleted_bytes = 0
        for fp, _, size, _, _ in all_segments:
            try:
                os.remove(fp)
                deleted_bytes += size
                deleted_count += 1
                current_mb -= (size / (1024 * 1024))
                if current_mb <= target_mb:
                    break
            except OSError:
                pass

        logger.info(f"Purged {deleted_count} oldest 5-frame segments ({deleted_bytes / (1024*1024):.2f} MB). Current storage: {current_mb:.2f} MB")

    def _monitor_loop(self):
        """Background thread continuously monitoring disk space."""
        while self.is_running:
            try:
                with self.lock:
                    self._purge_if_needed()
            except Exception as e:
                logger.error(f"Storage monitor error: {e}")
            time.sleep(1.0)

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive storage health and ring buffer telemetry."""
        used_mb = self.get_current_storage_mb()
        pct = round((used_mb / self.max_storage_mb) * 100, 1) if self.max_storage_mb > 0 else 0

        cam_counts = {}
        total_segs = 0
        min_time = None
        max_time = None

        if os.path.exists(self.recordings_dir):
            for cam_id in os.listdir(self.recordings_dir):
                cpath = os.path.join(self.recordings_dir, cam_id)
                if os.path.isdir(cpath):
                    files = [f for f in os.listdir(cpath) if f.endswith(".mp4")]
                    cam_counts[cam_id] = len(files)
                    total_segs += len(files)
                    for f in files:
                        try:
                            mt = os.path.getmtime(os.path.join(cpath, f))
                            if min_time is None or mt < min_time: min_time = mt
                            if max_time is None or mt > max_time: max_time = mt
                        except OSError:
                            pass

        retention_sec = round(max_time - min_time, 1) if (min_time and max_time) else 0.0

        return {
            "max_storage_mb": self.max_storage_mb,
            "used_storage_mb": used_mb,
            "used_percent": pct,
            "available_mb": round(max(0.0, self.max_storage_mb - used_mb), 2),
            "total_segments": total_segs,
            "segment_duration_frames": 5,
            "camera_segment_counts": cam_counts,
            "oldest_timestamp": min_time,
            "newest_timestamp": max_time,
            "retention_seconds": retention_sec,
            "status": "HEALTHY (Ring-Buffer Active)"
        }

    def get_recorded_timeline(self) -> Dict[str, Any]:
        """
        Returns list of synchronized 5-frame recorded segments for all cameras,
        allowing the web UI timeline scrubber to map exact recorded moments.
        """
        timeline = {}
        if not os.path.exists(self.recordings_dir):
            return {"cameras": {}, "retention_seconds": 0.0}

        for cam_id in sorted(os.listdir(self.recordings_dir)):
            cpath = os.path.join(self.recordings_dir, cam_id)
            if not os.path.isdir(cpath):
                continue
            files = sorted([f for f in os.listdir(cpath) if f.endswith(".mp4")])
            seg_list = []
            for f in files:
                fp = os.path.join(cpath, f)
                try:
                    mt = os.path.getmtime(fp)
                    sz = os.path.getsize(fp)
                    seg_list.append({
                        "name": f,
                        "timestamp": mt,
                        "size": sz,
                        "url": f"/api/storage/segment/{cam_id}/{f}"
                    })
                except OSError:
                    pass
            timeline[cam_id] = seg_list

        status = self.get_status()
        return {
            "cameras": timeline,
            "retention_seconds": status["retention_seconds"],
            "used_mb": status["used_storage_mb"],
            "max_mb": status["max_storage_mb"]
        }


# Global storage manager singleton instance (200 MB default)
storage_manager = StorageManager(default_quota_mb=200.0)
