#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 scripts/smoke-route-graph.py
python3 -m py_compile \
  overlay/usr/lib/carthing/carthing_runtime.py \
  overlay/usr/lib/carthing/session_runner.py \
  overlay/usr/lib/carthing/route_planner.py \
  overlay/usr/lib/carthing/trusted_device_registry.py \
  overlay/usr/lib/carthing/link_manager.py \
  overlay/usr/lib/carthing/enrollment_manager.py

echo "BAKE READINESS: OK (local userspace gates)"
