#!/bin/bash
# ==============================================================================
# AEGIS-PRO Surveillance System Simulator - Status Check Script
# ==============================================================================

echo "======================================================================"
echo " 🛡️  AEGIS-PRO SURVEILLANCE SYSTEM HEALTH CHECK"
echo "======================================================================"

echo -n "NVR Web Server (Port 8000)  : "
if curl -s http://localhost:8000/api/status >/dev/null; then
    echo "🟢 ONLINE"
    curl -s http://localhost:8000/api/status | python3 -m json.tool | grep -E "active_set|cpu_percent|camera_count|smart_status" | sed 's/^/   /'
else
    echo "🔴 OFFLINE"
fi

echo -n "MediaMTX RTSP Server (:8554) : "
if ss -tulpn 2>/dev/null | grep -q ":8554"; then
    echo "🟢 LISTENING"
else
    echo "🔴 OFFLINE"
fi

echo -n "MediaMTX WebRTC (:8889)      : "
if ss -tulpn 2>/dev/null | grep -q ":8889"; then
    echo "🟢 LISTENING"
else
    echo "🔴 OFFLINE"
fi

echo -n "Active FFmpeg RTSP Streams   : "
FF_COUNT=$(pgrep -f "rtsp://127.0.0.1:8554" | wc -l)
if [ "$FF_COUNT" -gt 0 ]; then
    echo "🟢 $FF_COUNT Cameras Publishing"
else
    echo "🔴 0 Cameras Publishing"
fi

echo "======================================================================"
