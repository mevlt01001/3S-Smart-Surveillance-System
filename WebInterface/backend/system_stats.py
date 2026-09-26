"""
System Health & Hardware Telemetry Service
Provides live statistics for GPU (nvidia-smi) and Triton Inference Server.
"""

import asyncio
import subprocess
from typing import Dict, Any
import httpx


async def get_system_telemetry() -> Dict[str, Any]:
    """Fetches GPU metrics and Triton Server health status."""
    stats = {
        "triton": {
            "status": "OFFLINE",
            "url": "http://localhost:8000",
            "models_ready": []
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

    # 1. Check Triton Server
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get("http://localhost:8000/v2/health/ready")
            if resp.status_code == 200:
                stats["triton"]["status"] = "READY"
                # Check models status
                for model in ["yoloe_detector", "anomaly_detector"]:
                    try:
                        m_resp = await client.get(f"http://localhost:8000/v2/models/{model}/ready")
                        if m_resp.status_code == 200:
                            stats["triton"]["models_ready"].append(model)
                    except Exception:
                        pass
    except Exception:
        stats["triton"]["status"] = "OFFLINE"

    # 2. Query nvidia-smi for GPU metrics
    def _query_gpu():
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

    loop = asyncio.get_running_loop()
    gpu_data = await loop.run_in_executor(None, _query_gpu)
    if gpu_data:
        stats["gpu"] = gpu_data

    return stats
