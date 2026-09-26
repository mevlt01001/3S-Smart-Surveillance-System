#!/bin/bash
# ==============================================================================
# AEGIS-PRO Surveillance System Simulator - Stop Script
# Gracefully terminates all NVR server, MediaMTX, and FFmpeg streaming processes
# ==============================================================================

echo "🛑 Stopping AEGIS-PRO Surveillance Simulator..."

# Kill python server, simulation and headless simulator
pkill -f "simulate_nvr.py" || true
pkill -f "run_simulation.py" || true
pkill -f "Camera_System_Simulator.*server:app" || true

# Kill mediamtx
pkill -f "bin/mediamtx" || true

# Kill ffmpeg camera stream publishers
pkill -f "rtsp://127.0.0.1:8554" || true

sleep 1
echo "✅ All surveillance simulator services stopped."
