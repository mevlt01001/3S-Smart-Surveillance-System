"""
System Health & Hardware Telemetry Service
Provides live statistics for GPU (nvidia-smi) and NVIDIA Triton Inference Server.
Exposes dedicated, real-time latencies for BOTH Object Detection and Anomaly Detection,
along with the overall Average GPU Inference Latency.

Only measured values are reported: a latency is None until the corresponding
model actually served a request (no invented "typical" numbers).
"""

import asyncio
import subprocess
import time
from typing import Dict, Any, Optional, List

import httpx

from .settings_service import settings_service

MODELS_TO_CHECK = ["safety_detector", "coco_detector", "yoloe_detector", "anomaly_detector"]

# Every open browser tab polls this endpoint. One probe (5 Triton calls + an nvidia-smi
# process) is shared by all of them for this long.
CACHE_TTL_SEC = 2.0
# A latency is shown only if the engine produced it within this many seconds
LATENCY_FRESH_SEC = 15.0
_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_cache_lock = asyncio.Lock()
_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    """
    One persistent client for all probes. Constructing an httpx client per request builds a
    TLS context (loads the CA bundle, ~40 ms of CPU) on the event loop — a periodic stall
    that showed up as a hiccup in every live video stream.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=1.2, verify=False)
    return _http_client


def _triton_base_url() -> str:
    url = settings_service.get_section("anomaly").get("triton_url") or "localhost:8000"
    return url if url.startswith("http") else f"http://{url}"


def _query_gpu() -> Optional[Dict[str, Any]]:
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5)
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                return {
                    "name": parts[0],
                    "vram_used_mb": int(parts[1]),
                    "vram_total_mb": int(parts[2]),
                    "utilization_gpu_pct": int(parts[3]),
                    "temperature_c": int(parts[4]),
                    "available": True
                }
    except Exception:
        pass
    return None


async def _probe() -> Dict[str, Any]:
    base_url = _triton_base_url()
    stats: Dict[str, Any] = {
        "triton": {
            "status": "OFFLINE",
            "url": base_url,
            "models_ready": [],
            "latency_ms": None,
            "avg_gpu_latency_ms": None,
            "object_detection_latency_ms": None,
            "anomaly_detection_latency_ms": None,
            "models_telemetry": {}
        },
        "gpu": {
            "name": "N/A",
            "vram_used_mb": 0,
            "vram_total_mb": 0,
            "utilization_gpu_pct": 0,
            "temperature_c": 0,
            "available": False
        }
    }

    loop = asyncio.get_running_loop()
    gpu_task = loop.run_in_executor(None, _query_gpu)

    # 1. Query Triton Server & Model Performance
    try:
        client = _client()
        if True:
            resp = await client.get(f"{base_url}/v2/health/ready")
            if resp.status_code == 200:
                stats["triton"]["status"] = "READY"

                async def _is_ready(model: str) -> Optional[str]:
                    try:
                        m_resp = await client.get(f"{base_url}/v2/models/{model}/ready")
                        return model if m_resp.status_code == 200 else None
                    except Exception:
                        return None

                ready_models: List[str] = [m for m in await asyncio.gather(*[_is_ready(m) for m in MODELS_TO_CHECK]) if m]
                stats["triton"]["models_ready"] = ready_models

                # 1A. Object Detection latency: smoothed round-trip of the live rule engine
                obj_lat: Optional[float] = None
                obj_active = False
                try:
                    from .live_detection_service import live_detection_service
                    val = live_detection_service.last_latency_ms
                    # only while the engine is really running (a value from minutes ago is not "current")
                    if val and val > 0 and (time.time() - live_detection_service.last_inference_ts) < LATENCY_FRESH_SEC:
                        obj_lat = round(float(val), 1)
                        obj_active = True
                except Exception:
                    pass

                # 1B. Anomaly Detection latency: per-stream share of the last batch
                anom_lat: Optional[float] = None
                anom_active = False
                try:
                    from .anomaly_service import anomaly_service
                    val = anomaly_service.last_latency_ms
                    if (val and val > 0 and anomaly_service.model_ready and anomaly_service.analysis_enabled
                            and (time.time() - anomaly_service.last_inference_ts) < LATENCY_FRESH_SEC):
                        anom_lat = round(float(val), 1)
                        anom_active = True
                except Exception:
                    pass

                # 1C. Average over the engines that are really running
                active_latencies = [l for l in (obj_lat, anom_lat) if l is not None and l > 0]
                avg_gpu_latency = round(sum(active_latencies) / len(active_latencies), 1) if active_latencies else None

                stats["triton"]["latency_ms"] = avg_gpu_latency  # Backward compatibility
                stats["triton"]["avg_gpu_latency_ms"] = avg_gpu_latency
                stats["triton"]["object_detection_latency_ms"] = obj_lat
                stats["triton"]["anomaly_detection_latency_ms"] = anom_lat

                stats["triton"]["models_telemetry"] = {
                    "object_detection": {
                        "name": "safety_detector",
                        "label": "Nesne Tespiti (YOLO)",
                        "latency_ms": obj_lat,
                        "active": obj_active,
                        "ready": "safety_detector" in ready_models
                    },
                    "anomaly_detection": {
                        "name": "anomaly_detector",
                        "label": "Anomali Tespiti (ViT)",
                        "latency_ms": anom_lat,
                        "active": anom_active,
                        "ready": "anomaly_detector" in ready_models
                    }
                }
    except Exception:
        stats["triton"]["status"] = "OFFLINE"

    # 2. nvidia-smi GPU metrics (ran concurrently with the Triton probe)
    gpu_data = await gpu_task
    if gpu_data:
        stats["gpu"] = gpu_data

    return stats


async def get_system_telemetry() -> Dict[str, Any]:
    """
    Returns GPU metrics and Triton Server telemetry: individual Object Detection latency,
    Anomaly Detection latency and the average GPU pipeline latency (short-lived cache).
    """
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
        return _cache["data"]
    async with _cache_lock:
        now = time.monotonic()
        if _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
            return _cache["data"]
        data = await _probe()
        _cache["data"] = data
        _cache["ts"] = time.monotonic()
        return data
