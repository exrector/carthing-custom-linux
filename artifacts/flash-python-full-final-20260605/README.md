# Unified runtime flash bundle

Created: 2026-06-05T12:01:22
Base bundle: artifacts/flash-python-full-20260605
Runtime source: (local repo root)
Runtime tree sha1: a4e79ba71e3382cba7c0d18d1eaec5c2c570b944

Hardware baseline:
- stock-plus rescue/profile kernel
- 512M rootfs
- default/rescue NCM (`CONFIG_USB_G_NCM=y`) for SSH/recovery after every boot
- optional USB functions are exposed only through profilectl/usb-profile
- USB Audio/Serial/HID/MIDI/Storage are switch targets, not boot defaults
- rootfs bake removes retired runtime files: classic_profile_probe.py, hid_pair.py, media_remote.py, media_remote_v3.py, now_playing_ui.py, system_menu.py, trusted_devices.py

This bundle is intended for `scripts/full-flash-bundle.py`.
