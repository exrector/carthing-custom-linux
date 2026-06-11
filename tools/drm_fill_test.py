#!/usr/bin/env python3
"""On-device DRM sanity check: solid colour fill, no GUI stack.

    ssh root@172.16.42.77 'python3 /usr/lib/carthing/../carthing/drm_fill_test.py'
    # or from repo on device:
    python3 tools/drm_fill_test.py

Expect a green screen for 5 s. Black screen with log "CRTC set" => pitch/format bug
or backlight off (check /sys/class/backlight/*/brightness).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "overlay", "usr", "lib", "carthing"))

from drm_display import DRMDisplay  # noqa: E402


def main():
    d = DRMDisplay()
    print(f"mode={d.width}x{d.height} pitch={d.pitch} size={d.size}", flush=True)
    d.fill_test((0, 200, 120))
    print("filled green — holding 5s", flush=True)
    time.sleep(5)
    d.fill_test((40, 40, 40))
    print("filled grey — done", flush=True)
    d.close()


if __name__ == "__main__":
    main()
