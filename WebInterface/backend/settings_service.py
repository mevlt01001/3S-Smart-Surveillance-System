"""
SETTINGS SERVICE (3S settings and configuration)
Manages persistent system configuration for Anomaly Inference, Video Recording,
CCTV/VMS Video Wall behavior, and Triton deployment parameters.
"""

import os
import json
import logging
import threading
from typing import Dict, Any

from .paths import data_path, atomic_write_json

logger = logging.getLogger("aegis_settings")

SETTINGS_FILE = data_path("settings.json")

LIVE_LAYOUTS = ("grid-1x1", "grid-2x2", "grid-3x2", "grid-4x3")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "anomaly": {
        "clip_len": 16,               # Triton model segment uzunluğu (16 kare)
        "threshold_normal": 25.0,     # %0 - %25 Yeşil (Normal)
        "threshold_warning": 50.0,    # %25 - %50 Turuncu (Şüpheli / Dikkat)
        "triton_url": "localhost:8000",
        "model_name": "anomaly_detector",
        "continuous_pipeline": True,  # Triton GPU'sunu boş bırakmayan kesintisiz döngü
        "batch_size": 4,              # Eşzamanlı Triton GPU kamera grup büyüklüğü (1-8)
    },
    "recording": {
        "auto_record_clips": True,    # Anomali süresi boyunca dinamik klip kaydı
        "tolerance_sec": 2.0,         # Olay birleştirme toleransı (sn): Anomali kesintiye uğrarsa bu süre boyunca klip bölünmez
        "padding_sec": 1.5,           # Ön ve arka güvenlik payı (sn): Olayın başı ve sonuna eklenen süre
        "max_clip_duration_sec": 60,  # Maksimum tekil klip güvenlik tavanı (sn)
        "max_stored_clips": 500,      # Maksimum saklanacak klip sayısı
        "max_storage_mb": 1000,       # Maksimum klip disk kotası (MB)
    },
    "live_wall": {
        "default_layout": "grid-3x2", # grid-1x1 | grid-2x2 | grid-3x2
        "alarm_borders": True,        # Anomali ve kural ihlalinde turuncu/kırmızı vuruş çerçevesi
        "hud_badges": True,           # Sol üst köşede nedenini açıklayan kompakt HUD rozeti
        "click_to_focus": True,       # Kameraya tıklandığında 1x1 tekil odak / büyütme modu
        "zero_latency_mode": True,    # Ağır çekimi ve gecikmeyi önleyen sıfır-tampon modu
    }
}


def _num(value: Any, fallback: float, lo: float, hi: float) -> float:
    """Coerces to a finite float clamped into [lo, hi]; falls back on garbage input."""
    try:
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            return fallback
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, v))


def _clean_number(v: float) -> Any:
    return int(v) if float(v).is_integer() else round(v, 2)


class SettingsService:
    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.load()

    def _sanitize(self):
        """
        Keeps every known parameter inside a range the engines can actually run with,
        whatever a client (or a hand-edited settings.json) supplied.
        """
        d = DEFAULT_SETTINGS
        for section in ("anomaly", "recording", "live_wall"):
            if not isinstance(self.settings.get(section), dict):
                self.settings[section] = json.loads(json.dumps(d[section]))

        a = self.settings["anomaly"]
        da = d["anomaly"]
        # Left over from earlier versions; no part of the system ever read them
        for obsolete in ("history_seconds", "sampling_fps", "threshold_critical"):
            a.pop(obsolete, None)
        a["clip_len"] = 16  # fixed by the exported model input shape [3, 16, 224, 224]
        t_normal = _num(a.get("threshold_normal"), da["threshold_normal"], 1.0, 95.0)
        t_warning = _num(a.get("threshold_warning"), da["threshold_warning"], 2.0, 99.0)
        if t_warning <= t_normal:
            t_warning = min(99.0, t_normal + 1.0)
        a["threshold_normal"] = _clean_number(t_normal)
        a["threshold_warning"] = _clean_number(t_warning)
        a["batch_size"] = int(_num(a.get("batch_size"), da["batch_size"], 1, 8))
        url = str(a.get("triton_url") or "").strip()
        for prefix in ("http://", "https://"):
            if url.lower().startswith(prefix):
                url = url[len(prefix):]
        a["triton_url"] = url.rstrip("/") or da["triton_url"]
        a["model_name"] = str(a.get("model_name") or "").strip() or da["model_name"]
        a["continuous_pipeline"] = bool(a.get("continuous_pipeline", True))

        r = self.settings["recording"]
        dr = d["recording"]
        r["auto_record_clips"] = bool(r.get("auto_record_clips", True))
        r["tolerance_sec"] = _clean_number(_num(r.get("tolerance_sec"), dr["tolerance_sec"], 0.5, 10.0))
        r["padding_sec"] = _clean_number(_num(r.get("padding_sec"), dr["padding_sec"], 0.0, 10.0))
        r["max_clip_duration_sec"] = _clean_number(_num(r.get("max_clip_duration_sec"), dr["max_clip_duration_sec"], 5.0, 300.0))
        r["max_stored_clips"] = int(_num(r.get("max_stored_clips"), dr["max_stored_clips"], 10, 5000))
        r["max_storage_mb"] = int(_num(r.get("max_storage_mb"), dr["max_storage_mb"], 50, 100000))

        w = self.settings["live_wall"]
        dw = d["live_wall"]
        if w.get("default_layout") not in LIVE_LAYOUTS:
            w["default_layout"] = dw["default_layout"]
        for key in ("alarm_borders", "hud_badges", "click_to_focus", "zero_latency_mode"):
            w[key] = bool(w.get(key, True))

    def load(self):
        """Loads settings from disk or initializes defaults."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                # Deep merge defaults with disk data to ensure all keys exist
                self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
                for section, vals in disk_data.items():
                    if section in self.settings and isinstance(vals, dict):
                        self.settings[section].update(vals)
                    else:
                        self.settings[section] = vals
                self._sanitize()
                return
            except Exception as e:
                logger.error(f"Settings file corrupted, using defaults: {e}")
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.save()

    def save(self):
        """Saves current settings to disk atomically."""
        try:
            atomic_write_json(SETTINGS_FILE, self.settings)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get_all(self) -> Dict[str, Any]:
        """Returns all configuration sections."""
        return self.settings

    def get_section(self, section: str) -> Dict[str, Any]:
        """Returns a specific section or default."""
        return self.settings.get(section, DEFAULT_SETTINGS.get(section, {}))

    def update(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Updates, validates and saves settings."""
        with self._lock:
            for section, vals in (new_settings or {}).items():
                if not isinstance(vals, dict):
                    continue  # every settings section is an object; ignore malformed input
                if isinstance(self.settings.get(section), dict):
                    self.settings[section].update(vals)
                else:
                    self.settings[section] = vals
            self._sanitize()
            self.save()
            return self.settings

    def reset_defaults(self) -> Dict[str, Any]:
        """Resets all settings back to factory defaults."""
        with self._lock:
            self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
            self.save()
            return self.settings


settings_service = SettingsService()
