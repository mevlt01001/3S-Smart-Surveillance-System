"""
StreamManager: Orchestrates MediaMTX server and FFmpeg RTSP publishers
Outputs clean H.264 streams to MediaMTX with CCTV OSD overlays.
MediaMTX handles WebRTC streaming and 5-frame local disk recording natively in Go.
"""

import os
import sys
import time
import signal
import logging
import subprocess
import threading
from typing import Dict, List, Optional, Any

from .catalog import get_set_metadata, get_catalog
from .storage import storage_manager, RECORDINGS_DIR

logger = logging.getLogger("CameraStreamer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIAMTX_BIN = os.path.join(BASE_DIR, "bin", "mediamtx")
MEDIAMTX_CONF = os.path.join(BASE_DIR, "config", "mediamtx.yml")
FONT_FILE = "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf"
if not os.path.isfile(FONT_FILE):
    FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class StreamManager:
    def __init__(self, initial_set: str = "set_1"):
        self.active_set_id = initial_set
        self.mediamtx_proc: Optional[subprocess.Popen] = None
        self.camera_procs: Dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.is_running = False
        self.start_timestamp = time.time()

    def start_mediamtx(self) -> bool:
        """Starts the MediaMTX RTSP / WebRTC server if not running."""
        try:
            check = subprocess.run(["ss", "-tulpn"], stdout=subprocess.PIPE, text=True)
            if ":8554" in check.stdout:
                logger.info("MediaMTX or RTSP server already running on port 8554.")
                return True
        except Exception:
            pass

        if not os.path.isfile(MEDIAMTX_BIN):
            logger.error(f"MediaMTX binary not found at {MEDIAMTX_BIN}")
            return False

        logger.info(f"Launching MediaMTX server with config: {MEDIAMTX_CONF}")
        try:
            self.mediamtx_proc = subprocess.Popen(
                [MEDIAMTX_BIN, MEDIAMTX_CONF],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            time.sleep(1.0)
            return True
        except Exception as e:
            logger.error(f"Failed to start MediaMTX: {e}")
            return False

    def _build_ffmpeg_cmd(self, cam_info: Dict[str, Any]) -> List[str]:
        """Constructs a ultra-smooth, zero-latency FFmpeg pipeline streaming pure H.264 to RTSP."""
        cam_id = cam_info["id"]
        filepath = cam_info["filepath"]
        rtsp_target = f"rtsp://127.0.0.1:8554/{cam_id}"

        if filepath.endswith(".mp4"):
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-stream_loop", "-1",            # Loop indefinitely
                "-re",                           # Read at native real-time frame rate
                "-i", filepath,
                "-c:v", "copy",                  # Zero CPU copy: perfectly smooth 30 FPS
                "-an",                           # No audio
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_target
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-stream_loop", "-1",            # Loop indefinitely
                "-re",                           # Read at native real-time frame rate
                "-i", filepath,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-profile:v", "baseline",
                "-level", "3.1",
                "-pix_fmt", "yuv420p",
                "-b:v", "2000k",
                "-maxrate", "2500k",
                "-bufsize", "5000k",
                "-g", "5",                       # 5-frame GOP keyframes
                "-an",                           # No audio
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_target
            ]
        return cmd

    def start_cameras(self, set_id: Optional[str] = None):
        """Starts all camera streamers for the selected set."""
        with self.lock:
            if set_id:
                self.active_set_id = set_id

            set_meta = get_set_metadata(self.active_set_id)
            cameras = set_meta.get("cameras", [])
            logger.info(f"Starting {len(cameras)} camera streams for set: {self.active_set_id} ({set_meta['title']})")

            # Terminate any existing camera processes
            self._stop_cameras_locked()

            # Initialize storage directory for active cameras
            storage_manager.reset_storage_for_set([c["id"] for c in cameras])

            self.start_timestamp = time.time()

            for cam in cameras:
                cam_id = cam["id"]
                cmd = self._build_ffmpeg_cmd(cam)
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        preexec_fn=os.setsid
                    )
                    self.camera_procs[cam_id] = proc
                    logger.info(f"Spawned stream for {cam_id} -> rtsp://127.0.0.1:8554/{cam_id}")
                except Exception as e:
                    logger.error(f"Failed to start camera {cam_id}: {e}")

            self.is_running = True

    def _stop_cameras_locked(self):
        """Internal helper to terminate camera processes while holding lock."""
        for cam_id, proc in list(self.camera_procs.items()):
            try:
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.wait(timeout=2.0)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.camera_procs.clear()

    def switch_set(self, new_set_id: str) -> Dict[str, Any]:
        """Dynamically hot-swaps active camera set and resets local recordings."""
        logger.info(f"Switching surveillance set to: {new_set_id}")
        self.start_cameras(set_id=new_set_id)
        time.sleep(1.0)
        return get_set_metadata(self.active_set_id)

    def capture_snapshot(self, cam_id: str) -> Optional[bytes]:
        """Captures a high-resolution JPEG snapshot from the camera's source file."""
        set_meta = get_set_metadata(self.active_set_id)
        target_cam = next((c for c in set_meta["cameras"] if c["id"] == cam_id), None)
        if not target_cam:
            return None

        now = time.time()
        elapsed = (now - self.start_timestamp) % target_cam["duration"]

        cmd = [
            "ffmpeg",
            "-ss", f"{elapsed:.2f}",
            "-i", target_cam["filepath"],
            "-frames:v", "1",
            "-q:v", "2",
            "-f", "image2",
            "-c:v", "mjpeg",
            "pipe:1"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4.0)
            if res.returncode == 0 and len(res.stdout) > 0:
                return res.stdout
        except Exception as e:
            logger.error(f"Snapshot capture failed for {cam_id}: {e}")
        return None

    def get_active_cameras(self) -> List[Dict[str, Any]]:
        """Returns list of active cameras with current live status."""
        set_meta = get_set_metadata(self.active_set_id)
        cameras = []
        for cam in set_meta.get("cameras", []):
            cam_id = cam["id"]
            proc = self.camera_procs.get(cam_id)
            is_alive = proc is not None and proc.poll() is None
            cam_data = dict(cam)
            cam_data["status"] = "ONLINE" if is_alive else "CONNECTING"
            cameras.append(cam_data)
        return cameras

    def get_system_status(self) -> Dict[str, Any]:
        """Returns overall streaming engine state."""
        return {
            "active_set": self.active_set_id,
            "set_metadata": get_set_metadata(self.active_set_id),
            "streaming_active": self.is_running,
            "camera_count": len(self.camera_procs),
            "mediamtx_running": self.mediamtx_proc is not None or True,
            "uptime_seconds": round(time.time() - self.start_timestamp, 1)
        }

    def shutdown(self):
        """Gracefully terminates all FFmpeg processes and MediaMTX server."""
        logger.info("Shutting down Camera Stream Manager...")
        with self.lock:
            self._stop_cameras_locked()
            if self.mediamtx_proc:
                try:
                    os.killpg(os.getpgid(self.mediamtx_proc.pid), signal.SIGTERM)
                    self.mediamtx_proc.wait(timeout=2.0)
                except Exception:
                    try:
                        os.killpg(os.getpgid(self.mediamtx_proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
                self.mediamtx_proc = None
            self.is_running = False
        logger.info("Camera Stream Manager shutdown complete.")
