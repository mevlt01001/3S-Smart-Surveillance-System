"""
Camera Fleet Management and Live Snapshot Service
- Persists registered cameras to cameras_db.json
- Verifies ONVIF device parameters, Profiles (S/G/T), RTSP and Snapshot endpoints
- Multi-tier snapshot fetcher (HTTP ONVIF Snapshot -> RTSP Frame Grab -> Styled Fallback Card)
"""

import asyncio
import json
import os
import socket
import time
import urllib.parse
from typing import Dict, List, Optional, Any, Tuple
import cv2
import httpx
import numpy as np

from .onvif_core import ONVIFClient, parse_scopes

DB_PATH = os.path.join(os.path.dirname(__file__), "cameras_db.json")


class CameraService:
    def __init__(self):
        self.cameras: Dict[str, Dict[str, Any]] = {}
        self._snapshot_cache: Dict[str, Tuple[bytes, float]] = {}  # camera_id -> (jpeg_bytes, timestamp)
        self._last_mtime: float = 0.0
        self.load_from_disk()

    def load_from_disk(self, force: bool = False):
        """Loads registered cameras from JSON database if modified."""
        if os.path.exists(DB_PATH):
            try:
                mtime = os.path.getmtime(DB_PATH)
                if force or mtime != self._last_mtime:
                    with open(DB_PATH, "r", encoding="utf-8") as f:
                        self.cameras = json.load(f)
                    self._last_mtime = mtime
            except Exception as e:
                print(f"[CameraService] Error loading {DB_PATH}: {e}")
                if force:
                    self.cameras = {}
        else:
            self.cameras = {}
            self._last_mtime = 0.0

    def save_to_disk(self):
        """Saves registered cameras to JSON database."""
        if not self.cameras and os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 10:
            # Güvenlik: Dolu DB'nin kazara boş bir sözlük ile ezilmesini önle
            return
        try:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cameras, f, indent=2, ensure_ascii=False)
            if os.path.exists(DB_PATH):
                self._last_mtime = os.path.getmtime(DB_PATH)
        except Exception as e:
            print(f"[CameraService] Error saving {DB_PATH}: {e}")

    def get_all(self) -> List[Dict[str, Any]]:
        """Returns all cameras as a sorted list."""
        self.load_from_disk()
        return list(self.cameras.values())

    def get_by_id(self, camera_id: str) -> Optional[Dict[str, Any]]:
        self.load_from_disk()
        return self.cameras.get(camera_id)

    def update_camera(
        self,
        camera_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Updates camera display name and descriptive purpose/notes."""
        self.load_from_disk()
        camera = self.cameras.get(camera_id)
        if not camera:
            return None

        if name is not None and name.strip():
            camera["name"] = name.strip()
        if description is not None:
            camera["description"] = description.strip()

        self.cameras[camera_id] = camera
        self.save_to_disk()
        return camera

    def delete_camera(self, camera_id: str) -> bool:
        self.load_from_disk()
        if camera_id in self.cameras:
            del self.cameras[camera_id]
            if camera_id in self._snapshot_cache:
                del self._snapshot_cache[camera_id]
            self.save_to_disk()
            return True
        return False

    async def probe_and_register(
        self,
        ip: str,
        port: int = 80,
        username: str = "",
        password: str = "",
        custom_name: str = "",
        rtsp_port: int = 554
    ) -> Dict[str, Any]:
        """
        Executes standard ONVIF device handshake:
        1. Time sync (GetSystemDateAndTime)
        2. Device Info (Manufacturer, Model, Firmware, Serial)
        3. Capabilities (Media Service URI)
        4. Profiles (Profile S/G/T detection, Resolution, FPS)
        5. Stream & Snapshot URIs
        """
        self.load_from_disk()
        camera_id = f"cam_{ip.replace('.', '_')}_{port}"
        existing_cam = self.cameras.get(camera_id)
        existing_desc = existing_cam.get("description", "") if existing_cam else ""
        existing_name = existing_cam.get("name", "") if existing_cam else ""

        xaddr = f"http://{ip}:{port}/onvif/device_service"

        client = ONVIFClient(xaddr=xaddr, username=username, password=password, timeout=4.0)

        # Base camera structure
        camera_data = {
            "id": camera_id,
            "ip": ip,
            "port": port,
            "rtsp_port": rtsp_port,
            "username": username,
            "password": password,
            "name": custom_name or existing_name or f"Camera {ip}",
            "description": existing_desc,
            "manufacturer": "Generic ONVIF",
            "model": "IP Camera",
            "firmware_version": "N/A",
            "serial_number": "N/A",
            "status": "online",
            "status_message": "Bağlantı Kuruldu",
            "profiles_supported": ["Profile S"],
            "resolution": "1920x1080",
            "encoding": "H.264",
            "framerate": 25,
            "stream_uri": f"rtsp://{ip}:{rtsp_port}/live",
            "snapshot_uri": None,
            "profiles_detail": [],
            "last_seen": time.time()
        }

        try:
            # 1. Sync Time
            await client.sync_time()

            # 2. Get Device Information
            try:
                dev_info = await client.get_device_information()
                camera_data["manufacturer"] = dev_info.get("manufacturer") or "ONVIF Device"
                camera_data["model"] = dev_info.get("model") or "IP Camera"
                camera_data["firmware_version"] = dev_info.get("firmware_version") or "N/A"
                camera_data["serial_number"] = dev_info.get("serial_number") or "N/A"
                if not custom_name:
                    camera_data["name"] = f"{camera_data['manufacturer']} {camera_data['model']}"
            except Exception as e:
                # If authentication failed
                if "401" in str(e) or "Unauthorized" in str(e) or "FailedAuthentication" in str(e):
                    camera_data["status"] = "auth_error"
                    camera_data["status_message"] = "Kimlik Doğrulama Hatası (Şifre Yanlış)"
                else:
                    camera_data["status_message"] = f"Cihaz Bilgisi Alınamadı: {e}"

            # 3. Get Capabilities & Media Service
            await client.get_capabilities()

            # 4. Get Profiles
            profiles = await client.get_profiles()
            if profiles:
                camera_data["profiles_detail"] = profiles
                primary = profiles[0]
                camera_data["resolution"] = f"{primary['width']}x{primary['height']}"
                camera_data["framerate"] = primary["framerate"]
                camera_data["encoding"] = "H.265" if "265" in primary["encoding"] else "H.264"

                # Check Profile S/T/G
                supported = ["Profile S"]
                if "265" in primary["encoding"] or any("265" in p.get("encoding", "") for p in profiles):
                    supported.append("Profile T")
                camera_data["profiles_supported"] = supported

                # 5. Get Stream URI
                stream_uri = await client.get_stream_uri(primary["token"])
                if stream_uri:
                    camera_data["stream_uri"] = stream_uri

                # 6. Get Snapshot URI
                snap_uri = await client.get_snapshot_uri(primary["token"])
                if snap_uri:
                    camera_data["snapshot_uri"] = snap_uri

        except Exception as e:
            print(f"[CameraService] Probe failed for {ip}:{port}: {e}")
            if "auth_error" not in camera_data["status"]:
                camera_data["status"] = "offline"
                camera_data["status_message"] = "Cihaza Erişilemedi"

        self.cameras[camera_id] = camera_data
        self.save_to_disk()
        return camera_data

    async def get_camera_snapshot(self, camera_id: str) -> Tuple[bytes, str]:
        """
        Fetches an ultra-low latency JPEG snapshot for the camera.
        Uses 800ms cache to avoid hammering hardware.
        Cascade:
          Tier 1: Camera HTTP Snapshot URI (ONVIF standard)
          Tier 2: Fast TCP pre-check + RTSP Frame Grab via OpenCV TCP transport
          Tier 3: Dynamically rendered high-tech dark slate/orange preview card
        """
        self.load_from_disk()
        camera = self.get_by_id(camera_id)
        if not camera:
            return self._generate_fallback_image("Kamera Bulunamadı", "Bilinmeyen Cihaz"), "image/jpeg"

        now = time.time()
        # Check cache (800ms validity)
        if camera_id in self._snapshot_cache:
            cached_bytes, cached_time = self._snapshot_cache[camera_id]
            if now < cached_time + 0.8:
                return cached_bytes, "image/jpeg"

        loop = asyncio.get_running_loop()

        # Tier 1: Try HTTP Snapshot URI if available
        if camera.get("snapshot_uri"):
            try:
                auth = None
                if camera.get("username") and camera.get("password"):
                    auth = (camera["username"], camera["password"])
                async with httpx.AsyncClient(timeout=1.0, verify=False) as client:
                    resp = await client.get(camera["snapshot_uri"], auth=auth)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        if camera.get("status") != "online" and camera.get("status") != "auth_error":
                            camera["status"] = "online"
                            camera["status_message"] = "Bağlantı Aktif"
                            self.save_to_disk()
                        self._snapshot_cache[camera_id] = (resp.content, now)
                        return resp.content, "image/jpeg"
            except Exception:
                pass

        # Tier 2: RTSP Frame Capture via OpenCV in executor thread
        stream_uri = camera.get("stream_uri")
        if stream_uri and stream_uri.startswith("rtsp://"):
            def _grab_rtsp_frame():
                try:
                    parsed = urllib.parse.urlparse(stream_uri)
                    host = parsed.hostname
                    port = parsed.port or 554
                    if not host:
                        return None
                    # Ultra-fast non-blocking TCP socket check (0.4s max timeout)
                    # Prevents OpenCV FFMPEG from locking worker thread for 30s on offline hosts!
                    with socket.create_connection((host, port), timeout=0.4):
                        pass
                except Exception:
                    # RTSP port closed or unreachable - fail fast, DO NOT hang OpenCV!
                    return None

                cap = None
                try:
                    # Enforce TCP transport and 1.5s network timeout
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;1500000"
                    cap = cv2.VideoCapture(stream_uri, cv2.CAP_FFMPEG)
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        success, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                        if success:
                            return buf.tobytes()
                except Exception:
                    pass
                finally:
                    if cap is not None:
                        cap.release()
                return None

            try:
                frame_bytes = await asyncio.wait_for(loop.run_in_executor(None, _grab_rtsp_frame), timeout=1.8)
            except Exception:
                frame_bytes = None

            if frame_bytes:
                if camera.get("status") != "online" and camera.get("status") != "auth_error":
                    camera["status"] = "online"
                    camera["status_message"] = "Bağlantı Aktif"
                    self.save_to_disk()
                self._snapshot_cache[camera_id] = (frame_bytes, now)
                return frame_bytes, "image/jpeg"

        # Tier 3: Styled High-Tech Camera Card Frame
        if camera.get("status") == "online":
            camera["status"] = "offline"
            camera["status_message"] = "Cihaza Erişilemedi"
            self.save_to_disk()

        status_text = camera.get("status_message", "Bağlantı Aranıyor")
        device_label = f"{camera.get('manufacturer', '')} {camera.get('model', '')} ({camera.get('ip')})"
        fallback_bytes = self._generate_fallback_image(device_label, status_text, is_auth_error=(camera.get("status") == "auth_error"))
        
        # Cache fallback for 3.0 seconds to prevent rapid hammering on offline cameras
        self._snapshot_cache[camera_id] = (fallback_bytes, now + 2.2)
        return fallback_bytes, "image/jpeg"

    def _generate_fallback_image(self, title: str, subtitle: str, is_auth_error: bool = False) -> bytes:
        """
        Generates an aesthetic 640x360 dark slate / orange fallback frame with high-tech HUD grid.
        """
        w, h = 640, 360
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Deep slate background #0F131D
        img[:] = (29, 19, 15)  # BGR

        # Draw subtle grid lines
        grid_color = (45, 30, 24)
        for x in range(0, w, 40):
            cv2.line(img, (x, 0), (x, h), grid_color, 1)
        for y in range(0, h, 40):
            cv2.line(img, (0, y), (w, y), grid_color, 1)

        # Center target / viewfinder circle
        center = (w // 2, h // 2 - 20)
        accent_color = (51, 133, 255) if not is_auth_error else (50, 50, 240)  # Amber Orange or Alert Red in BGR
        cv2.circle(img, center, 45, accent_color, 2)
        cv2.circle(img, center, 6, accent_color, -1)

        # Crosshairs
        cv2.line(img, (center[0] - 65, center[1]), (center[0] - 50, center[1]), accent_color, 2)
        cv2.line(img, (center[0] + 50, center[1]), (center[0] + 65, center[1]), accent_color, 2)
        cv2.line(img, (center[0], center[1] - 65), (center[0], center[1] - 50), accent_color, 2)
        cv2.line(img, (center[0], center[1] + 50), (center[0], center[1] + 65), accent_color, 2)

        # Text labels
        font = cv2.FONT_HERSHEY_SIMPLEX
        title_text = title[:35]
        cv2.putText(img, title_text, (25, h - 65), font, 0.65, (240, 240, 240), 2, cv2.LINE_AA)
        cv2.putText(img, subtitle[:45], (25, h - 35), font, 0.5, accent_color, 1, cv2.LINE_AA)

        # ONVIF Standard watermark
        cv2.putText(img, "ONVIF PROFILE S/G/T", (w - 200, 30), font, 0.45, (120, 130, 150), 1, cv2.LINE_AA)

        # Timestamp
        time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(img, time_str, (25, 30), font, 0.45, (120, 130, 150), 1, cv2.LINE_AA)

        success, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if success else b""
