#!/usr/bin/env bash
# ==============================================================================
# AegisVision Commercial Surveillance System WebInterface Launcher
# Starts FastAPI + Uvicorn server on port 8500
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.conda/bin/python"

echo "=================================================================="
echo " Starting AegisVision Commercial WebInterface Server"
echo " Host: 0.0.0.0 | Port: 8500"
echo " Target: http://localhost:8500"
echo "=================================================================="

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# Local settings (.env at the repository root, see .env.example).
# A variable that is already set in the environment keeps its value.
if [ -f "${PROJECT_ROOT}/.env" ]; then
  while IFS='=' read -r name value; do
    case "${name}" in ''|\#*) continue ;; esac
    if [ -z "${!name+x}" ]; then export "${name}=${value}"; fi
  done < "${PROJECT_ROOT}/.env"
fi

exec "${PYTHON_BIN}" -m uvicorn WebInterface.backend.server:app \
  --host 0.0.0.0 \
  --port 8500 \
  --reload \
  --reload-dir "${SCRIPT_DIR}/backend" \
  --timeout-graceful-shutdown 5 \
  --log-level info

