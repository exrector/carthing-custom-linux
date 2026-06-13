#!/usr/bin/env python3
"""Check Car Thing route/standby architectural invariants."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = [
    ROOT / "overlay/usr/lib/carthing/app_state.py",
    ROOT / "overlay/usr/lib/carthing/a2dp_bridge.py",
    ROOT / "overlay/usr/lib/carthing/carthing_runtime.py",
    ROOT / "overlay/usr/lib/carthing/transfer_service.py",
    ROOT / "overlay/usr/lib/carthing/intents.py",
    ROOT / "overlay/usr/lib/carthing/settings_service.py",
]

BANNED = (
    "default_speaker",
    "select_default_speaker",
    "clear_connected_speakers",
    "_speaker_connections",
    "_speaker_connectors",
    "_connect_tasks",
    "_speaker_backoff",
    "_standby_connecting",
)


def main() -> int:
    failures = []
    for path in CORE_FILES:
        text = path.read_text()
        for token in BANNED:
            if token in text:
                failures.append(f"{path.relative_to(ROOT)} contains banned token {token!r}")

    bridge = (ROOT / "overlay/usr/lib/carthing/a2dp_bridge.py").read_text()
    required = (
        "class SpeakerRuntime",
        "self._speaker_runtimes",
        "def _speaker_runtime",
        "connector_owned",
        "active_route_speaker_address",
    )
    for token in required:
        if token not in bridge:
            failures.append(f"a2dp_bridge.py missing per-device runtime marker {token!r}")
    if "runtime.connector.rtp_channel is not None" not in bridge:
        failures.append("a2dp_bridge.py standby loop must require media/RTP readiness, not just ACL")

    app_state = (ROOT / "overlay/usr/lib/carthing/app_state.py").read_text()
    if "SELF_OUTPUT_KEY = \"carthing\"" not in app_state:
        failures.append("app_state.py missing Play Now self-output key")
    if "def select_active_route_output" not in app_state:
        failures.append("app_state.py missing active route output boundary")
    if "\"default\"" in app_state:
        failures.append("app_state.py still persists speaker default fields")
    if ".route_speaker_address()" in bridge:
        failures.append("a2dp_bridge.py reads pending route_speaker_address instead of active route")

    if failures:
        for failure in failures:
            print(f"ROUTE ARCH FAIL: {failure}")
        return 1
    print("ROUTE ARCH OK: per-device standby/runtime invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
