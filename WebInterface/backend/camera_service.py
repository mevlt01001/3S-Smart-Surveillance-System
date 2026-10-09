"""
Camera Fleet Management and Live Snapshot Service
- Persists registered cameras to cameras_db.json
- Verifies ONVIF device parameters, Profiles (S/G/T), RTSP and Snapshot endpoints
- One background RTSP worker per camera feeds live video, AI frames and clip history
- Stream health watchdog: a camera whose stream stalls is reported as "no signal"
  instead of silently showing its last frame as if it were live
"""

import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
from collections import deque
from typing import Dict, List, Optional, Any, Tuple, AsyncIterator

import cv2
import httpx
import numpy as np

from .onvif_core import ONVIFClient
from .paths import data_path, atomic_write_json, SHUTTING_DOWN

logger = logging.getLogger("aegis.cameras")

# Every camera already has its own worker thread. Letting OpenCV additionally fan each
# resize out to a 16-thread pool only adds lock contention and spinning helper threads.
cv2.setNumThreads(1)

DB_PATH = data_path("cameras_db.json")

# A stream is considered stalled when no new frame arrived for this long.
STREAM_STALE_SEC = 3.0
# Workers release their RTSP connection when nobody consumed frames for this long.
WORKER_IDLE_SEC = 120.0
# Upper bound for frames decoded/encoded per camera (surplus frames of faster sources are dropped).
MAX_OUTPUT_FPS = 30.0

_TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _ascii(text: str) -> str:
    """cv2.putText only renders ASCII: transliterate Turkish characters instead of printing '?'."""
    return str(text or "").translate(_TR_ASCII).encode("ascii", "replace").decode("ascii")


class CameraLiveWorker:
    """Maintains an active background RTSP video connection for a camera and caches frames for streaming & AI."""

    def __init__(self, camera_id: str, stream_uri: str, clip_window_sec: float = 30.0, decoder_threads: int = 1):
        self.camera_id = camera_id
        self.stream_uri = stream_uri
        # FFmpeg defaults to one decoder thread per CPU core *per camera*. Frame-threaded
        # decoding delays output by (threads - 1) frames (~0.6 s at 25 FPS on 16 cores) and
        # multiplies memory; a single thread decodes up to 1080p in real time with minimal latency.
        self.decoder_threads = max(1, int(decoder_threads))
        self.latest_jpeg: Optional[bytes] = None
        self.latest_bgr: Optional[np.ndarray] = None
        self.last_accessed: float = time.time()
        self.last_frame_ts: float = 0.0
        self.frame_seq: int = 0
        self.session_frames: int = 0  # frames received since the current RTSP connection was opened
        self.resuming: bool = False   # waking up from standby (not a signal loss)
        self.fps: float = 0.0
        self.state: str = "connecting"  # connecting | live | stalled | idle
        self.state_since: float = time.time()
        self.running = True
        self.lock = threading.Lock()
        # Time-bounded ring buffer of (timestamp, jpeg_bytes) for incident clips. Sized from the
        # recording settings (longest possible clip + padding) instead of a fixed frame count,
        # so RAM usage follows what can actually be recorded.
        self.clip_window_sec = float(clip_window_sec)
        self.clip_ring_buffer: deque = deque()
        # Dedicated ring buffer for zero-decode Triton 3D inference (pre-sized 224x224 RGB uint8)
        self.ai_ring_buffer: deque = deque(maxlen=32)
        self._listeners: set = set()
        self._preferred_uri: Optional[str] = None
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"RTSPWorker-{camera_id}")
        self.thread.start()

    # ------------------------------------------------------------------ state
    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.state_since = time.time()

    def is_live(self) -> bool:
        """True while fresh frames keep arriving from the camera."""
        if self.latest_jpeg is None:
            return False
        # A single frame right after a (re)connect can be a stale picture replayed from the
        # RTSP server's cache while the camera itself is still silent: wait for a second one.
        if self.session_frames < 2:
            return False
        # Low frame-rate cameras (1 FPS and below) legitimately have long gaps between frames
        stale_after = STREAM_STALE_SEC if self.fps >= 2.0 or self.fps <= 0.0 else max(STREAM_STALE_SEC, 5.0 / self.fps)
        return (time.time() - self.last_frame_ts) < stale_after

    def frame_age(self) -> Optional[float]:
        return (time.time() - self.last_frame_ts) if self.last_frame_ts else None

    # -------------------------------------------------------------- listeners
    def add_listener(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event):
        self._listeners.add((loop, event))

    def remove_listener(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event):
        self._listeners.discard((loop, event))

    def _notify_listeners(self):
        for item in tuple(self._listeners):
            loop, event = item
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                self._listeners.discard(item)

    # ---------------------------------------------------------------- capture
    def _get_candidate_uris(self) -> List[str]:
        """Provides primary stream URI and fallback localhost URI if stream is local simulator."""
        uris = [self.stream_uri]
        try:
            parsed = urllib.parse.urlparse(self.stream_uri)
            port = parsed.port or 8554
            if parsed.hostname not in ["127.0.0.1", "localhost"]:
                if parsed.username and parsed.password:
                    auth = f"{parsed.username}:{parsed.password}@"
                elif parsed.username:
                    auth = f"{parsed.username}@"
                else:
                    auth = ""
                local_uri = f"rtsp://{auth}127.0.0.1:{port}{parsed.path}"
                uris.append(local_uri)
                # Also candidate clean anonymous localhost URI
                clean_uri = f"rtsp://127.0.0.1:{port}{parsed.path}"
                if clean_uri not in uris:
                    uris.append(clean_uri)
        except Exception:
            pass
        # Try the URI that worked last time first so reconnects are fast
        if self._preferred_uri in uris:
            uris.remove(self._preferred_uri)
            uris.insert(0, self._preferred_uri)
        return uris

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        for uri in self._get_candidate_uris():
            if not self.running:
                return None
            cap = None
            try:
                cap = cv2.VideoCapture(
                    uri, cv2.CAP_FFMPEG,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
                        cv2.CAP_PROP_N_THREADS, self.decoder_threads,
                    ],
                )
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._preferred_uri = uri
                    return cap
            except Exception:
                pass
            if cap is not None:
                cap.release()
        return None

    def _sleep(self, seconds: float):
        end = time.time() + seconds
        while self.running and time.time() < end:
            time.sleep(0.1)

    def _run(self):
        backoff = 1.0
        while self.running:
            # Release the camera connection while nobody consumes frames
            if time.time() - self.last_accessed > WORKER_IDLE_SEC:
                self._set_state("idle")
                time.sleep(0.5)
                continue

            if self.state == "idle":
                self._set_state("connecting")
                self.resuming = True

            cap = self._open_capture()
            if cap is None:
                if self.state == "live":
                    self._set_state("stalled")
                self._sleep(backoff)
                backoff = min(backoff * 1.6, 10.0)
                continue

            backoff = 1.0
            try:
                self._pump(cap)
            except Exception:
                pass
            finally:
                cap.release()
            if self.running and self.state == "live":
                self._set_state("stalled")
                self._notify_listeners()

    def _pump(self, cap: cv2.VideoCapture):
        # Sources up to MAX_OUTPUT_FPS are passed through frame for frame. (Skipping by
        # arrival time would drop frames whenever network jitter bunches two of them together.)
        # Only genuinely faster sources are decimated, evenly, by frame count.
        try:
            source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            source_fps = 0.0
        if 0.0 < source_fps <= 120.0:
            keep_ratio = min(1.0, MAX_OUTPUT_FPS / source_fps)
            min_interval = 0.0
        else:
            keep_ratio = 1.0  # unknown rate: fall back to a time-based cap
            min_interval = (1.0 / MAX_OUTPUT_FPS) - 0.005
        keep_acc = 1.0
        last_emit = 0.0
        self.session_frames = 0
        last_ok = time.time()
        fps_window_start = time.time()
        fps_window_frames = 0

        while self.running and (time.time() - self.last_accessed <= WORKER_IDLE_SEC):
            # grab() blocks on the socket until the next frame (GIL released) and
            # keeps the RTSP queue flushed without the cost of a full decode+convert
            grab_started = time.time()
            if not cap.grab():
                if time.time() - last_ok > 4.0:
                    return
                time.sleep(0.02)
                continue
            now = time.time()
            if now - grab_started > 4.0:
                # The read ran into its timeout and FFmpeg handed out frames still sitting in the
                # decoder: seconds-old pictures that would be shown (and analysed) as "live".
                # Drop the session and reconnect instead.
                return
            last_ok = now

            keep_acc += keep_ratio
            if keep_acc < 1.0 or (min_interval and now - last_emit < min_interval):
                continue
            keep_acc -= 1.0
            ret, frame = cap.retrieve()
            if not ret or frame is None or frame.size == 0:
                continue
            last_emit = now

            # Downscale large frames to max 1280px width for fast encoding & smooth browser render
            h, w = frame.shape[:2]
            if w > 1280:
                scale = 1280.0 / w
                frame = cv2.resize(frame, (1280, int(h * scale)), interpolation=cv2.INTER_AREA)

            # Pre-resize to 224x224 RGB uint8 for zero-copy instant Triton AI inference.
            # (Resizing first and swapping channels on the small image is bit-identical to
            # converting the full frame first, but skips a full-resolution colour conversion.)
            rgb_224 = cv2.cvtColor(
                cv2.resize(frame, (224, 224), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2RGB
            )

            # Encode with JPEG quality 70 (crystal clear CCTV, fast encoding, low network load)
            success, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if not success:
                continue
            jpeg_bytes = buf.tobytes()

            fps_window_frames += 1
            if now - fps_window_start >= 2.0:
                self.fps = round(fps_window_frames / (now - fps_window_start), 1)
                fps_window_start = now
                fps_window_frames = 0

            with self.lock:
                self.latest_jpeg = jpeg_bytes
                self.latest_bgr = frame
                self.last_frame_ts = now
                self.frame_seq += 1
                self.session_frames += 1
                self.clip_ring_buffer.append((now, jpeg_bytes))
                cutoff = now - self.clip_window_sec
                while self.clip_ring_buffer and self.clip_ring_buffer[0][0] < cutoff:
                    self.clip_ring_buffer.popleft()
                self.ai_ring_buffer.append(rgb_224)
            if self.session_frames >= 2:
                self._set_state("live")
                self.resuming = False
            self._notify_listeners()

    # ---------------------------------------------------------------- readers
    def get_frame(self, touch: bool = True) -> Optional[bytes]:
        if touch:
            self.last_accessed = time.time()
        with self.lock:
            return self.latest_jpeg

    def get_frame_info(self, touch: bool = True) -> Tuple[Optional[bytes], int, float]:
        """Returns (jpeg_bytes, frame_seq, frame_timestamp) atomically."""
        if touch:
            self.last_accessed = time.time()
        with self.lock:
            return self.latest_jpeg, self.frame_seq, self.last_frame_ts

    def get_bgr_frame(self, touch: bool = True) -> Optional[np.ndarray]:
        if touch:
            self.last_accessed = time.time()
        with self.lock:
            return self.latest_bgr.copy() if self.latest_bgr is not None else None

    def get_clip_frames(self, duration_sec: float = 10.0, touch: bool = True) -> List[Tuple[float, bytes]]:
        """Returns buffered (timestamp, jpeg_bytes) within the last duration_sec for incident recording."""
        now = time.time()
        if touch:
            self.last_accessed = now
        cutoff = now - duration_sec
        with self.lock:
            return [(item[0], item[1]) for item in self.clip_ring_buffer if item[0] >= cutoff]

    def get_clip_frames_range(self, start_ts: float, end_ts: float, touch: bool = True) -> List[Tuple[float, bytes]]:
        """Returns buffered (timestamp, jpeg_bytes) within [start_ts, end_ts] for dynamic incident clip cutting."""
        if touch:
            self.last_accessed = time.time()
        with self.lock:
            return [(item[0], item[1]) for item in self.clip_ring_buffer if start_ts <= item[0] <= end_ts]

    def get_frame_at(self, ts: float) -> Optional[bytes]:
        """Returns the buffered JPEG closest to the given timestamp (used for incident snapshots)."""
        with self.lock:
            if not self.clip_ring_buffer:
                return self.latest_jpeg
            best = min(self.clip_ring_buffer, key=lambda item: abs(item[0] - ts))
            return best[1]

    def get_ai_frames(self, count: int = 16, touch: bool = True) -> List[np.ndarray]:
        """Returns the most recent `count` pre-resized 224x224 RGB frames for zero-decode Triton inference."""
        if touch:
            self.last_accessed = time.time()
        with self.lock:
            if not self.ai_ring_buffer:
                return []
            return list(self.ai_ring_buffer)[-count:]

    def stop(self):
        self.running = False
        self._notify_listeners()


class CameraService:
    def __init__(self):
        self.cameras: Dict[str, Dict[str, Any]] = {}
        self._snapshot_cache: Dict[str, Tuple[bytes, float]] = {}  # camera_id -> (jpeg_bytes, timestamp)
        self._placeholder_cache: Dict[str, Tuple[bytes, float]] = {}
        self._live_workers: Dict[str, CameraLiveWorker] = {}
        self._last_mtime: float = 0.0
        self._lock = threading.RLock()
        self.clip_window_sec: float = 30.0
        self.load_from_disk()
        self._auto_start_workers()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="CameraWatchdog")
        self._watchdog_thread.start()

    # ---------------------------------------------------------------- workers
    def _auto_start_workers(self):
        """Pre-starts live workers for registered cameras so initial streams load instantly."""
        for cam_id, cam in list(self.cameras.items()):
            stream_uri = cam.get("stream_uri")
            if stream_uri and stream_uri.startswith("rtsp://"):
                self.get_or_start_worker(cam_id, stream_uri)

    def _decoder_threads_for(self, camera_id: str) -> int:
        """1 decoder thread up to 1080p (lowest latency); a few more only for 4K-class streams."""
        try:
            cam = self.cameras.get(camera_id) or {}
            w, h = (int(v) for v in str(cam.get("resolution", "1920x1080")).lower().split("x")[:2])
            return 1 if (w * h) <= (1920 * 1088) else 4
        except Exception:
            return 1

    def get_or_start_worker(self, camera_id: str, stream_uri: str) -> CameraLiveWorker:
        """Returns or starts persistent background worker for this camera's RTSP feed."""
        with self._lock:
            worker = self._live_workers.get(camera_id)
            if not worker or not worker.running or worker.stream_uri != stream_uri:
                if worker:
                    worker.stop()
                worker = CameraLiveWorker(
                    camera_id, stream_uri,
                    clip_window_sec=self.clip_window_sec,
                    decoder_threads=self._decoder_threads_for(camera_id),
                )
                self._live_workers[camera_id] = worker
            return worker

    def get_worker(self, camera_id: str) -> Optional[CameraLiveWorker]:
        return self._live_workers.get(camera_id)

    def set_clip_window(self, seconds: float):
        """Sets how many seconds of video each camera keeps in RAM for incident clips."""
        self.clip_window_sec = max(10.0, float(seconds))
        for worker in list(self._live_workers.values()):
            worker.clip_window_sec = self.clip_window_sec

    def _stop_worker(self, camera_id: str):
        with self._lock:
            worker = self._live_workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def shutdown(self):
        """Stops every RTSP worker (called when the server exits)."""
        with self._lock:
            workers = list(self._live_workers.values())
        for worker in workers:
            worker.stop()

    def _watchdog_loop(self):
        """Keeps camera status in sync with the real stream state and reaps orphaned workers."""
        while not SHUTTING_DOWN.is_set():
            time.sleep(1.0)
            try:
                self.sync_stream_status()
            except Exception as e:
                logger.warning(f"Watchdog error: {e}")

    def sync_stream_status(self):
        changed = False
        with self._lock:
            # Workers of cameras that were removed (also via external DB edits) must not leak
            for cam_id in [cid for cid in self._live_workers if cid not in self.cameras]:
                self._stop_worker(cam_id)

            for cam_id, cam in self.cameras.items():
                worker = self._live_workers.get(cam_id)
                if not worker:
                    continue
                status = cam.get("status")
                if worker.is_live():
                    # (an ONVIF authentication problem stays visible even if video happens to flow)
                    if status not in ("online", "auth_error"):
                        cam["status"] = "online"
                        cam["status_message"] = "Bağlantı Aktif"
                        changed = True
                    cam["last_seen"] = worker.last_frame_ts
                elif worker.state != "idle":
                    # Was live and stopped: judge by the age of the last frame (independent of
                    # how long the decoder blocks before it notices). Never delivered a frame yet:
                    # it may simply be waiting for its first key frame (long-GOP cameras), so the
                    # initial connection gets more time.
                    if worker.last_frame_ts and not worker.resuming:
                        down_for, grace = time.time() - worker.last_frame_ts, 8.0
                    else:
                        down_for, grace = time.time() - worker.state_since, 20.0
                    if down_for > grace and status == "online":
                        cam["status"] = "offline"
                        cam["status_message"] = "Sinyal Yok (Video Akışı Kesildi)"
                        changed = True
        if changed:
            self.save_to_disk()

    def get_stream_health(self, camera_id: str) -> Dict[str, Any]:
        """Real-time stream state for UI badges: live flag, measured FPS and age of the last frame."""
        worker = self._live_workers.get(camera_id)
        if not worker:
            return {"stream_live": False, "stream_connecting": False, "stream_standby": False,
                    "stream_state": "none", "stream_fps": 0.0, "last_frame_age": None}
        live = worker.is_live()
        age = worker.frame_age()
        return {
            "stream_live": live,
            # connecting: first connection, or waking up after standby (neither is a signal loss)
            "stream_connecting": (not live) and worker.state == "connecting" and (not worker.last_frame_ts or worker.resuming),
            # standby: nobody is watching or analysing this camera, so its connection was released;
            # it reconnects automatically as soon as it is needed
            "stream_standby": (not live) and worker.state == "idle",
            "stream_state": "live" if live else worker.state if worker.state != "live" else "stalled",
            "stream_fps": worker.fps if live else 0.0,
            "last_frame_age": round(age, 1) if age is not None else None,
        }

    def public_view(self, camera: Dict[str, Any]) -> Dict[str, Any]:
        """API representation: adds live stream health and never exposes the stored password field."""
        view = {k: v for k, v in camera.items() if k != "password"}
        view.update(self.get_stream_health(camera.get("id", "")))
        return view

    # ------------------------------------------------------------ persistence
    def load_from_disk(self, force: bool = False):
        """Loads registered cameras from JSON database if modified."""
        with self._lock:
            if os.path.exists(DB_PATH):
                try:
                    mtime = os.path.getmtime(DB_PATH)
                    if force or mtime != self._last_mtime:
                        with open(DB_PATH, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            self.cameras = data
                        self._last_mtime = mtime
                except Exception as e:
                    logger.warning(f"Error loading {DB_PATH}: {e}")
                    if force:
                        self.cameras = {}
            else:
                self.cameras = {}
                self._last_mtime = 0.0

    def save_to_disk(self):
        """Saves registered cameras to JSON database (atomic write)."""
        with self._lock:
            try:
                atomic_write_json(DB_PATH, self.cameras)
                self._last_mtime = os.path.getmtime(DB_PATH)
            except Exception as e:
                logger.warning(f"Error saving {DB_PATH}: {e}")

    # ------------------------------------------------------------------- CRUD
    def get_all(self) -> List[Dict[str, Any]]:
        """Returns all cameras as a list."""
        self.load_from_disk()
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            if camera_id not in self.cameras:
                return False
            del self.cameras[camera_id]
            self._snapshot_cache.pop(camera_id, None)
            self._placeholder_cache.pop(camera_id, None)
            self.save_to_disk()
        # Stop the RTSP thread right away instead of leaking it
        self._stop_worker(camera_id)
        return True

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
                if not custom_name and not existing_name:
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
            elif camera_data["status"] == "online":
                # Device answered but exposes no media profile we can use
                camera_data["status"] = "offline"
                camera_data["status_message"] = "ONVIF Medya Profili Alınamadı"

        except Exception as e:
            logger.warning(f"Probe failed for {ip}:{port}: {e}")
            if "auth_error" not in camera_data["status"]:
                camera_data["status"] = "offline"
                camera_data["status_message"] = "Cihaza Erişilemedi"

        with self._lock:
            if not existing_cam:
                # Discovery often reports the same generic name for every device ("Hikvision"):
                # give a newly added camera a distinguishable display name.
                camera_data["name"] = self._unique_name(camera_data["name"], camera_id)
            self.cameras[camera_id] = camera_data
            self.save_to_disk()

        # Start pulling video immediately so the first view is instant
        stream_uri = camera_data.get("stream_uri")
        if stream_uri and stream_uri.startswith("rtsp://"):
            self.get_or_start_worker(camera_id, stream_uri)
        return camera_data

    def _unique_name(self, name: str, camera_id: str) -> str:
        taken = {str(c.get("name", "")).strip().lower() for cid, c in self.cameras.items() if cid != camera_id}
        base = (name or "Kamera").strip()
        if base.lower() not in taken:
            return base
        n = 2
        while f"{base} {n}".lower() in taken:
            n += 1
        return f"{base} {n}"

    # -------------------------------------------------------------- snapshots
    async def get_camera_snapshot(self, camera_id: str) -> Tuple[bytes, str]:
        """
        Fetches an ultra-low latency JPEG snapshot for the camera.
        Tier 1: Live RTSP Worker memory buffer (instant 0ms retrieval).
        Tier 2: Camera HTTP Snapshot URI (ONVIF standard) for cameras without an RTSP stream.
        Tier 3: "No signal" card (last frame dimmed + banner) so stale video is never shown as live.
        """
        camera = self.get_by_id(camera_id)
        if not camera:
            return self._generate_fallback_image("Kamera Bulunamadı", "Bilinmeyen Cihaz"), "image/jpeg"

        now = time.time()
        stream_uri = camera.get("stream_uri")

        # Tier 1: Real-time Live RTSP Stream Worker (instant 0ms memory buffer)
        if stream_uri and stream_uri.startswith("rtsp://"):
            worker = self.get_or_start_worker(camera_id, stream_uri)
            live_frame = worker.get_frame(touch=True)
            if not live_frame and worker.state == "connecting":
                # Give worker up to 300ms to capture initial frame if just spawned
                for _ in range(6):
                    await asyncio.sleep(0.05)
                    live_frame = worker.get_frame(touch=True)
                    if live_frame:
                        break

            if live_frame and worker.is_live():
                self._snapshot_cache[camera_id] = (live_frame, now)
                return live_frame, "image/jpeg"
            return self.get_placeholder_frame(camera, worker), "image/jpeg"

        # Fast cache check for Tier 2 (prevents redundant concurrent socket connects)
        cached = self._snapshot_cache.get(camera_id)
        if cached and now < cached[1] + 0.8:
            return cached[0], "image/jpeg"

        # Tier 2: Try HTTP Snapshot URI if available
        if camera.get("snapshot_uri"):
            try:
                auth = None
                if camera.get("username") and camera.get("password"):
                    auth = (camera["username"], camera["password"])
                async with httpx.AsyncClient(timeout=1.5, verify=False) as client:
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

        # Tier 3: Styled High-Tech Camera Card Frame
        if camera.get("status") == "online":
            camera["status"] = "offline"
            camera["status_message"] = "Cihaza Erişilemedi"
            self.save_to_disk()

        fallback_bytes = self.get_placeholder_frame(camera, None)
        self._snapshot_cache[camera_id] = (fallback_bytes, now + 1.0)
        return fallback_bytes, "image/jpeg"

    def get_placeholder_frame(self, camera: Dict[str, Any], worker: Optional[CameraLiveWorker]) -> bytes:
        """Returns the image shown while a camera delivers no live video (cached for 1s per camera)."""
        camera_id = camera.get("id", "")
        now = time.time()
        cached = self._placeholder_cache.get(camera_id)
        if cached and now - cached[1] < 1.0:
            return cached[0]

        last_jpeg = worker.latest_jpeg if worker else None
        if worker and last_jpeg is not None:
            waking = worker.state == "idle" or worker.resuming
            image = self._generate_no_signal_image(
                last_jpeg, worker.last_frame_ts, title="BAGLANIYOR" if waking else "SINYAL YOK"
            )
        elif worker and worker.state == "connecting" and (now - worker.state_since) < 8.0:
            image = self._generate_fallback_image(camera.get("name", "Kamera"), "Canlı Akış Bağlanıyor...")
        else:
            status_text = camera.get("status_message") or "Sinyal Yok"
            if worker:
                status_text = "Sinyal Yok - Yeniden Bağlanılıyor..."
            device_label = f"{camera.get('name') or ''} ({camera.get('ip')})"
            image = self._generate_fallback_image(
                device_label, status_text, is_auth_error=(camera.get("status") == "auth_error")
            )
        self._placeholder_cache[camera_id] = (image, now)
        return image

    def get_camera_clip_frames(self, camera_id: str, duration_sec: float = 5.0) -> List[Tuple[float, bytes]]:
        """Returns the buffered JPEG frames from the last duration_sec for incident clip recording."""
        camera = self.get_by_id(camera_id)
        if not camera:
            return []
        stream_uri = camera.get("stream_uri")
        if not stream_uri:
            return []
        worker = self.get_or_start_worker(camera_id, stream_uri)
        return worker.get_clip_frames(duration_sec=duration_sec)

    def get_camera_clip_frames_range(self, camera_id: str, start_ts: float, end_ts: float) -> List[Tuple[float, bytes]]:
        """Returns the buffered JPEG frames between start_ts and end_ts for dynamic incident clip recording."""
        camera = self.get_by_id(camera_id)
        if not camera:
            return []
        stream_uri = camera.get("stream_uri")
        if not stream_uri:
            return []
        worker = self.get_or_start_worker(camera_id, stream_uri)
        return worker.get_clip_frames_range(start_ts, end_ts)

    def get_camera_ai_frames(self, camera_id: str, count: int = 16) -> List[np.ndarray]:
        """Returns the most recent pre-sized 224x224 RGB frames for zero-copy AI inference."""
        camera = self.get_by_id(camera_id)
        if not camera:
            return []
        stream_uri = camera.get("stream_uri")
        if not stream_uri:
            return []
        worker = self.get_or_start_worker(camera_id, stream_uri)
        return worker.get_ai_frames(count=count)

    def get_camera_jpeg_at(self, camera_id: str, ts: Optional[float] = None) -> Optional[bytes]:
        """Returns the real JPEG frame of a camera at (or nearest to) a moment, for incident evidence."""
        worker = self._live_workers.get(camera_id)
        if not worker:
            return None
        if ts is None:
            return worker.get_frame(touch=False)
        return worker.get_frame_at(ts)

    # --------------------------------------------------------------- streaming
    async def iter_frames(self, camera_id: str, max_fps: float = 0.0) -> AsyncIterator[bytes]:
        """
        Event-driven live frame source shared by the WebSocket and MJPEG endpoints.
        Wakes exactly when the RTSP worker publishes a new frame (no polling jitter),
        always yields the newest frame (slow clients skip frames instead of lagging),
        and yields a "no signal" card once per second while the camera is down.
        """
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        worker: Optional[CameraLiveWorker] = None
        last_seq = -1
        last_sent = 0.0
        last_placeholder = 0.0
        min_gap = (1.0 / max_fps) if max_fps and max_fps > 0 else 0.0

        try:
            while not SHUTTING_DOWN.is_set():
                camera = self.get_by_id(camera_id)
                if not camera:
                    yield self._generate_fallback_image("Kamera Bulunamadı", "Bilinmeyen Cihaz")
                    return

                stream_uri = camera.get("stream_uri")
                current = (
                    self.get_or_start_worker(camera_id, stream_uri)
                    if (stream_uri and stream_uri.startswith("rtsp://")) else None
                )
                if current is not worker:
                    if worker:
                        worker.remove_listener(loop, event)
                    worker = current
                    if worker:
                        worker.add_listener(loop, event)
                    last_seq = -1

                event.clear()
                now = time.time()
                if worker and worker.is_live():
                    jpeg, seq, _ = worker.get_frame_info(touch=True)
                    if jpeg is not None and seq != last_seq and (now - last_sent) >= min_gap * 0.9:
                        last_seq = seq
                        last_sent = now
                        yield jpeg
                elif now - last_placeholder >= 1.0:
                    last_placeholder = now
                    if worker:
                        worker.last_accessed = now
                    last_seq = -1
                    yield self.get_placeholder_frame(camera, worker)

                try:
                    await asyncio.wait_for(event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
        finally:
            if worker:
                worker.remove_listener(loop, event)

    async def mjpeg_stream_generator(self, camera_id: str, request: Any = None):
        """
        Continuously yields real-time multipart JPEG frames (MJPEG stream) for the
        enlarged camera preview. Stops as soon as the client disconnects.
        """
        try:
            async for frame_bytes in self.iter_frames(camera_id):
                header = (
                    f"--frame\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame_bytes)}\r\n\r\n"
                ).encode("ascii")
                yield header + frame_bytes + b"\r\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass

    # ------------------------------------------------------------ placeholders
    def _generate_no_signal_image(self, last_jpeg: bytes, last_ts: float, title: str = "SINYAL YOK") -> bytes:
        """Dims the last received frame and stamps it so stale video can't be mistaken for live video."""
        try:
            img = cv2.imdecode(np.frombuffer(last_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("decode failed")
            h, w = img.shape[:2]
            if w > 960:
                scale = 960.0 / w
                img = cv2.resize(img, (960, int(h * scale)), interpolation=cv2.INTER_AREA)
                h, w = img.shape[:2]
            gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            img = cv2.addWeighted(gray, 0.35, np.zeros_like(gray), 0.65, 0)

            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = max(0.6, w / 640.0)
            (tw, th), _ = cv2.getTextSize(title, font, scale * 1.2, 2)
            cx, cy = w // 2, h // 2
            cv2.rectangle(img, (cx - tw // 2 - 18, cy - th - 22), (cx + tw // 2 + 18, cy + 34), (20, 20, 40), -1)
            accent = (80, 80, 240) if title == "SINYAL YOK" else (200, 170, 120)
            cv2.rectangle(img, (cx - tw // 2 - 18, cy - th - 22), (cx + tw // 2 + 18, cy + 34), accent, 2)
            cv2.putText(img, title, (cx - tw // 2, cy - 4), font, scale * 1.2, accent, 2, cv2.LINE_AA)
            sub = "Son kare: " + time.strftime("%H:%M:%S", time.localtime(last_ts))
            (sw, _), _ = cv2.getTextSize(sub, font, scale * 0.5, 1)
            cv2.putText(img, sub, (cx - sw // 2, cy + 22), font, scale * 0.5, (200, 200, 210), 1, cv2.LINE_AA)
            success, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if success:
                return buf.tobytes()
        except Exception:
            pass
        return self._generate_fallback_image("Kamera", "Sinyal Yok")

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

        # Text labels (ASCII transliterated: OpenCV's built-in fonts cannot draw Turkish glyphs)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img, _ascii(title)[:35], (25, h - 65), font, 0.65, (240, 240, 240), 2, cv2.LINE_AA)
        cv2.putText(img, _ascii(subtitle)[:55], (25, h - 35), font, 0.5, accent_color, 1, cv2.LINE_AA)

        # ONVIF Standard watermark
        cv2.putText(img, "ONVIF PROFILE S/G/T", (w - 200, 30), font, 0.45, (120, 130, 150), 1, cv2.LINE_AA)

        # Timestamp
        time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(img, time_str, (25, 30), font, 0.45, (120, 130, 150), 1, cv2.LINE_AA)

        success, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if success else b""


# Global singleton instance
camera_service = CameraService()
