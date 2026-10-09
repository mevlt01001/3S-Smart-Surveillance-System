"""
Change Detection Module
=======================
Detects structural/occupancy changes in predefined zones (e.g., emergency exits,
fire cabinets) by comparing a captured reference snapshot against the live frame.

Algorithm: SSIM (Structural Similarity Index Measure)
  - Robustly handles minor lighting variations unlike simple pixel-diff methods.
  - Works on the masked polygon region of the frame, not the whole image.
  - Uses contour analysis on the difference map to classify whether change is
    significant (blocked access) or trivial (lighting/noise).
"""

import cv2
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from .paths import data_path

logger = logging.getLogger("change_detector")

REFS_DIR = data_path("change_refs")
os.makedirs(REFS_DIR, exist_ok=True)

SSIM_ALARM_THRESHOLD = 0.72
SSIM_WARNING_THRESHOLD = 0.88
MIN_CONTOUR_AREA_PX = 400
RESIZE_TO = (160, 120)


def _ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    k = 11
    sigma = 1.5
    gk = cv2.getGaussianKernel(k, sigma)
    window = gk @ gk.T
    mu1 = cv2.filter2D(img1, -1, window)
    mu2 = cv2.filter2D(img2, -1, window)
    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu12 = mu1 * mu2
    sigma1_sq = cv2.filter2D(img1 ** 2, -1, window) - mu1_sq
    sigma2_sq = cv2.filter2D(img2 ** 2, -1, window) - mu2_sq
    sigma12 = cv2.filter2D(img1 * img2, -1, window) - mu12
    num = (2 * mu12 + C1) * (2 * sigma12 + C2)
    den = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    ssim_map = num / (den + 1e-8)
    return float(np.mean(ssim_map))


def _extract_zone_patch(
    frame_bgr: np.ndarray,
    points_normalized: List[Dict[str, float]],
    frame_wh: Tuple[int, int],
    out_size: Tuple[int, int] = RESIZE_TO,
) -> Optional[np.ndarray]:
    if not points_normalized or len(points_normalized) < 3:
        return None
    W, H = frame_wh
    poly = np.array(
        [(int(p["x"] * W), int(p["y"] * H)) for p in points_normalized],
        dtype=np.int32,
    )
    x, y, bw, bh = cv2.boundingRect(poly)
    x = max(0, x); y = max(0, y)
    bw = min(bw, W - x); bh = min(bh, H - y)
    if bw < 8 or bh < 8:
        return None
    roi = frame_bgr[y: y + bh, x: x + bw].copy()
    mask = np.zeros((bh, bw), dtype=np.uint8)
    shifted = poly - np.array([x, y])
    cv2.fillPoly(mask, [shifted], 255)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray[mask == 0] = 0
    patch = cv2.resize(gray, out_size, interpolation=cv2.INTER_AREA)
    return patch


class ZoneChangeState:
    def __init__(self):
        self.reference_patch: Optional[np.ndarray] = None
        self.reference_ts: float = 0.0
        self.last_ssim: float = 1.0
        self.last_check_ts: float = 0.0
        self.alarm: bool = False
        self.alarm_level: str = "clear"
        self.alarm_since: float = 0.0
        self.description: str = ""
        self.zone_name: str = ""


class ChangeDetector:
    """
    Manages reference snapshots and SSIM-based change detection for all
    registered camera zones of type 'change_detection'. Thread-safe.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[Tuple[str, str], ZoneChangeState] = {}
        self._load_persisted_refs()

    def _ref_path(self, camera_id: str, zone_id: str) -> str:
        safe_cam = camera_id.replace("/", "_").replace(":", "_")
        safe_zone = zone_id.replace("/", "_").replace(":", "_")
        return os.path.join(REFS_DIR, f"ref_{safe_cam}__{safe_zone}.npy")

    def _meta_path(self, camera_id: str, zone_id: str) -> str:
        safe_cam = camera_id.replace("/", "_").replace(":", "_")
        safe_zone = zone_id.replace("/", "_").replace(":", "_")
        return os.path.join(REFS_DIR, f"meta_{safe_cam}__{safe_zone}.json")

    def _load_persisted_refs(self):
        if not os.path.exists(REFS_DIR):
            return
        for fname in os.listdir(REFS_DIR):
            if not fname.startswith("meta_") or not fname.endswith(".json"):
                continue
            meta_path = os.path.join(REFS_DIR, fname)
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                cam_id = meta.get("camera_id")
                zone_id = meta.get("zone_id")
                if not cam_id or not zone_id:
                    continue
                npy_path = self._ref_path(cam_id, zone_id)
                if not os.path.exists(npy_path):
                    continue
                patch = np.load(npy_path)
                key = (cam_id, zone_id)
                with self._lock:
                    if key not in self._states:
                        self._states[key] = ZoneChangeState()
                    s = self._states[key]
                    s.reference_patch = patch
                    s.reference_ts = meta.get("ts", time.time())
                    s.zone_name = meta.get("zone_name", "")
                    s.description = meta.get("description", "")
                logger.info(f"[ChangeDetector] Ref yüklendi: {cam_id}/{zone_id}")
            except Exception as e:
                logger.warning(f"[ChangeDetector] Ref yüklenemedi {fname}: {e}")

    def capture_reference(
        self,
        camera_id: str,
        zone_id: str,
        frame_bgr: np.ndarray,
        points_normalized: List[Dict[str, float]],
        zone_name: str = "",
        description: str = "",
    ) -> bool:
        H, W = frame_bgr.shape[:2]
        patch = _extract_zone_patch(frame_bgr, points_normalized, (W, H))
        if patch is None:
            logger.warning(f"[ChangeDetector] Referans alınamadı: geçersiz poligon ({zone_id})")
            return False

        key = (camera_id, zone_id)
        now = time.time()
        with self._lock:
            if key not in self._states:
                self._states[key] = ZoneChangeState()
            s = self._states[key]
            s.reference_patch = patch
            s.reference_ts = now
            s.zone_name = zone_name
            s.description = description
            s.alarm = False
            s.alarm_level = "clear"
            s.alarm_since = 0.0

        np.save(self._ref_path(camera_id, zone_id), patch)
        meta = {
            "camera_id": camera_id,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "description": description,
            "ts": now,
        }
        with open(self._meta_path(camera_id, zone_id), "w") as f:
            json.dump(meta, f, ensure_ascii=False)
        logger.info(f"[ChangeDetector] Referans alındı: {camera_id}/{zone_id}")
        return True

    def delete_reference(self, camera_id: str, zone_id: str):
        key = (camera_id, zone_id)
        with self._lock:
            self._states.pop(key, None)
        for p in [self._ref_path(camera_id, zone_id), self._meta_path(camera_id, zone_id)]:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass

    def delete_camera_references(self, camera_id: str):
        """Drops every stored reference of a camera that was removed from the fleet."""
        with self._lock:
            keys = [k for k in self._states if k[0] == camera_id]
        for cam_id, zone_id in keys:
            self.delete_reference(cam_id, zone_id)

    def check_frame(
        self,
        camera_id: str,
        zone_id: str,
        frame_bgr: np.ndarray,
        points_normalized: List[Dict[str, float]],
        frame_wh: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        if frame_wh is None:
            H, W = frame_bgr.shape[:2]
            frame_wh = (W, H)

        W, H = frame_wh
        default = {
            "has_reference": False, "ssim": 1.0, "alarm": False,
            "alarm_level": "clear", "change_pct": 0.0,
            "zone_id": zone_id, "zone_name": "", "description": "",
        }

        key = (camera_id, zone_id)
        with self._lock:
            state = self._states.get(key)
            if state is None or state.reference_patch is None:
                return default
            ref_patch = state.reference_patch.copy()
            zone_name = state.zone_name
            description = state.description

        live_patch = _extract_zone_patch(frame_bgr, points_normalized, (W, H))
        if live_patch is None:
            return {**default, "has_reference": True, "zone_name": zone_name}

        ssim_score = max(-1.0, min(1.0, _ssim(ref_patch, live_patch)))

        diff = cv2.absdiff(ref_patch, live_patch)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        significant_area = sum(cv2.contourArea(c) for c in contours if cv2.contourArea(c) >= MIN_CONTOUR_AREA_PX)
        total_area = RESIZE_TO[0] * RESIZE_TO[1]
        change_pct = min(100.0, round((significant_area / total_area) * 100, 1))

        if ssim_score < SSIM_ALARM_THRESHOLD:
            alarm_level = "alarm"
            is_alarm = True
        elif ssim_score < SSIM_WARNING_THRESHOLD:
            alarm_level = "warning"
            is_alarm = change_pct > 10.0
        else:
            alarm_level = "clear"
            is_alarm = False

        with self._lock:
            state = self._states.get(key)
            if state:
                state.last_ssim = ssim_score
                state.last_check_ts = time.time()
                state.alarm = is_alarm
                state.alarm_level = alarm_level
                if is_alarm and state.alarm_since == 0.0:
                    state.alarm_since = time.time()
                elif not is_alarm:
                    state.alarm_since = 0.0

        return {
            "has_reference": True,
            "ssim": round(ssim_score, 4),
            "alarm": is_alarm,
            "alarm_level": alarm_level,
            "change_pct": change_pct,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "description": description,
        }

    def get_zone_state(self, camera_id: str, zone_id: str) -> Optional[Dict[str, Any]]:
        key = (camera_id, zone_id)
        with self._lock:
            state = self._states.get(key)
            if not state:
                return None
            return {
                "camera_id": camera_id,
                "zone_id": zone_id,
                "zone_name": state.zone_name,
                "has_reference": state.reference_patch is not None,
                "reference_ts": state.reference_ts,
                "last_ssim": state.last_ssim,
                "alarm": state.alarm,
                "alarm_level": state.alarm_level,
                "alarm_since": state.alarm_since,
                "last_check_ts": state.last_check_ts,
                "description": state.description,
            }


change_detector = ChangeDetector()
