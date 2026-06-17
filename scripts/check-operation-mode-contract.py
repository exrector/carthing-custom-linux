#!/usr/bin/env python3
"""Check product mode resource invariants."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay/usr/lib/carthing"))

import operation_mode  # noqa: E402
from resource_policy import RuntimeResourcePolicy  # noqa: E402
from app_state import AppState  # noqa: E402
from runtime_model import RuntimeModel  # noqa: E402


def main() -> int:
    failures = []

    if operation_mode.DEFAULT != operation_mode.PLAYNOW:
        failures.append("operation_mode.DEFAULT must be PLAYNOW")

    play = operation_mode.resources(operation_mode.PLAYNOW).as_dict()
    comm = operation_mode.resources(operation_mode.COMMUTATOR).as_dict()
    reserved = operation_mode.resources(operation_mode.RESERVED).as_dict()

    for key in ("speaker_standby", "receiver_stream", "route_patchbay", "speaker_scan"):
        if play[key]:
            failures.append(f"playnow unexpectedly enables {key}")
        if reserved[key]:
            failures.append(f"reserved unexpectedly enables {key}")
    for key in ("speaker_standby", "receiver_stream", "route_patchbay"):
        if not comm[key]:
            failures.append(f"commutator must enable {key}")
    if comm["speaker_scan"]:
        failures.append("commutator must not enable background speaker_scan; scans are manual/event-driven")

    app_state = AppState()
    if app_state.operation_mode != operation_mode.DEFAULT:
        failures.append(
            f"AppState default operation_mode {app_state.operation_mode!r} != {operation_mode.DEFAULT!r}"
        )

    model = RuntimeModel()
    model.set_operation_mode(operation_mode.PLAYNOW, play)
    policy = RuntimeResourcePolicy(cpufreq_root="/missing-cpufreq", zram_sysfs="/missing-zram")
    model.set_resource_policy(policy.apply(operation_mode.PLAYNOW, tier="interactive", reason="test"))
    bt = model.bt_block()
    if bt.get("operation_mode") != operation_mode.PLAYNOW:
        failures.append("RuntimeModel does not publish operation_mode")
    if bt.get("mode_resources", {}).get("speaker_standby"):
        failures.append("RuntimeModel publishes speaker_standby in Play Now")
    if "resource_policy" not in bt:
        failures.append("RuntimeModel does not publish resource_policy diagnostics")
    elif bt["resource_policy"].get("cpu_policies") != []:
        failures.append("ResourcePolicy empty-sysfs test should publish an empty cpu_policies list")
    elif "sensors" not in bt["resource_policy"]:
        failures.append("ResourcePolicy does not publish sensor diagnostics")

    app_state_text = (ROOT / "overlay/usr/lib/carthing/app_state.py").read_text()
    if 'operation_mode = "commutator"' in app_state_text:
        failures.append("AppState still hardcodes commutator as initial operation mode")

    runtime_text = (ROOT / "overlay/usr/lib/carthing/carthing_runtime.py").read_text()
    if "async def _apply_operation_mode" not in runtime_text:
        failures.append("carthing_runtime lacks central _apply_operation_mode")
    if 'reason="route_activate"' not in runtime_text:
        failures.append("route activation does not apply operation mode")
    if 'reason="settings"' not in runtime_text:
        failures.append("settings mode handler does not use central operation mode apply")
    if 'reason="safe_unplug"' not in runtime_text:
        failures.append("safe unplug does not pass through central Play Now mode teardown")
    if "_apply_resource_policy" not in runtime_text:
        failures.append("carthing_runtime does not apply mode-aware resource policy")

    transfer_text = (ROOT / "overlay/usr/lib/carthing/transfer_service.py").read_text()
    if "async def apply_operation_mode" not in transfer_text:
        failures.append("TransferService lacks apply_operation_mode")
    if "_stop_all_receiver_streams" not in transfer_text:
        failures.append("TransferService lacks all-receiver stream teardown for Play Now")
    if "link_manager.start()" in runtime_text:
        failures.append("runtime still starts periodic LinkManager polling")

    init_text = (ROOT / "overlay/usr/libexec/carthing/init-wrapper").read_text()
    if "S11-zram" not in init_text:
        failures.append("init-wrapper does not run optional S11-zram before runtime")

    if failures:
        for failure in failures:
            print(f"OPERATION MODE FAIL: {failure}")
        return 1
    print("OPERATION MODE OK: playnow/commutator/reserved resource contract holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
