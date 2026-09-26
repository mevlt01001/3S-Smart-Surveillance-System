#!/bin/bash
# ==============================================================================
# AEGIS-PRO Surveillance System Simulator - Master Startup Script (Headless CLI)
# Usage:
#   ./start.sh
#   ./start.sh --dir video_sets/set_1 --segment-minutes 60 --quota-mb 500
#   ./start.sh video_sets/set_2 60 500
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Clean up old lingering processes if any
./stop.sh >/dev/null 2>&1 || true

# If positional shorthand is used (e.g. ./start.sh video_sets/set_1 60 500):
if [[ $# -eq 1 && ! "$1" =~ ^- && -d "$1" ]]; then
    exec python3 simulate_nvr.py --dir "$1"
elif [[ $# -eq 2 && ! "$1" =~ ^- && -d "$1" ]]; then
    exec python3 simulate_nvr.py --dir "$1" --segment-minutes "$2"
elif [[ $# -eq 3 && ! "$1" =~ ^- && -d "$1" ]]; then
    exec python3 simulate_nvr.py --dir "$1" --segment-minutes "$2" --quota-mb "$3"
else
    # Forward all flags as-is (e.g. ./start.sh --dir video_sets/set_1 --segment-minutes 60)
    exec python3 simulate_nvr.py "$@"
fi
