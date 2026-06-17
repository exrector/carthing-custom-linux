#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
PYCACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/carthing-bake-readiness-pycache.XXXXXX")"
trap 'rm -rf "$PYCACHE_DIR"' EXIT
export PYTHONPYCACHEPREFIX="$PYCACHE_DIR"

python3 scripts/smoke-route-graph.py
python3 scripts/check-bumble-vendor.py
python3 scripts/check-route-architecture.py
python3 scripts/check-operation-mode-contract.py
python3 - <<'PY'
import importlib.util
from pathlib import Path

script = Path("scripts/bake-unified-runtime-rootfs.py")
spec = importlib.util.spec_from_file_location("bake_unified_runtime_rootfs", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

actual = mod.runtime_tree_sha1(Path("overlay/usr/lib/carthing"))
expected = mod.EXPECTED_RUNTIME_TREE_SHA1
if actual != expected:
    raise SystemExit(f"runtime tree sha mismatch: {actual} != {expected}")
print(f"RUNTIME TREE SHA OK: {actual}")
PY
python3 -m py_compile \
  overlay/usr/lib/carthing/carthing_runtime.py \
  overlay/usr/lib/carthing/session_runner.py \
  overlay/usr/lib/carthing/route_planner.py \
  overlay/usr/lib/carthing/trusted_device_registry.py \
  overlay/usr/lib/carthing/link_manager.py \
  overlay/usr/lib/carthing/enrollment_manager.py

echo "BAKE READINESS: OK (local userspace gates)"
