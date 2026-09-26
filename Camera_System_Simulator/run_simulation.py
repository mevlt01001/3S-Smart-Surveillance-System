#!/usr/bin/env python3
"""
AEGIS-PRO Simulation Launcher CLI
Allows starting the simulator with a specific video set and network configuration.
Example:
    python3 run_simulation.py --set set_1 --port 8000
    python3 run_simulation.py --set set_5 --port 8090
"""

import os
import sys
import argparse
import uvicorn
import logging

from core.catalog import get_catalog
from core.streamer import StreamManager

def main():
    parser = argparse.ArgumentParser(description="AEGIS-PRO CCTV & NVR Surveillance Simulator")
    parser.add_argument("--set", type=str, default="set_1", help="Initial video set to stream (e.g., set_1 .. set_11)")
    parser.add_argument("--port", type=int, default=8000, help="Web server port (default: 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Web server bind host (default: 0.0.0.0)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")

    args = parser.parse_args()

    cat = get_catalog()
    if args.set not in cat:
        print(f"❌ Error: Set '{args.set}' not found.")
        print(f"Available sets: {', '.join(cat.keys())}")
        sys.exit(1)

    print("=" * 70)
    print(" 🛡️  AEGIS-PRO ENTERPRISE CCTV & NVR SURVEILLANCE SIMULATOR")
    print("=" * 70)
    print(f"▶ Initial Video Set    : {args.set.upper()} ({cat[args.set]['title']})")
    print(f"▶ Cameras in Set       : {cat[args.set]['camera_count']} cameras ({cat[args.set]['resolution_label']})")
    print(f"▶ NVR Web Console      : http://localhost:{args.port}")
    print(f"▶ MediaMTX RTSP Server : rtsp://localhost:8554/<cam_id>")
    print(f"▶ WebRTC WHEP Engine   : http://localhost:8889/<cam_id>/whep")
    print("=" * 70)

    # Set environment variable so server.py picks up the initial set
    os.environ["INITIAL_SURVEILLANCE_SET"] = args.set

    import server
    server.stream_manager.active_set_id = args.set

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
