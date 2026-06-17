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

mods = []
for script in (Path("scripts/bake-unified-runtime-rootfs.py"), Path("tools/bake-rootfs.py")):
    spec = importlib.util.spec_from_file_location(script.stem.replace("-", "_"), script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mods.append((script, mod))

actual = mods[0][1].runtime_tree_sha1(Path("overlay/usr/lib/carthing"))
expected = mods[0][1].EXPECTED_RUNTIME_TREE_SHA1
if actual != expected:
    raise SystemExit(f"runtime tree sha mismatch: {actual} != {expected}")
for script, mod in mods[1:]:
    if mod.EXPECTED_RUNTIME_TREE_SHA1 != expected:
        raise SystemExit(
            f"{script} EXPECTED_RUNTIME_TREE_SHA1 mismatch: "
            f"{mod.EXPECTED_RUNTIME_TREE_SHA1} != {expected}"
        )
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
