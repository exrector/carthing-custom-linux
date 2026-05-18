# MFi / iAP2 Revival Track

Status on 2026-05-18:

- The current working `device1-v1` baseline is the custom Buildroot Linux userspace
  with `Bumble + HID + AMS + btattach`.
- That baseline intentionally excludes `bluez`, `bluetoothd`, and D-Bus from the
  target image.
- The preserved legacy Apple-oriented stack was different:
  `BlueZ Profile1 + RFCOMM + iAP2 + apple_mfi auth`.

Hard facts from the live device:

- `NO_BLUETOOTHD`
- `NO_DBUS_DAEMON`
- `NO_GDBUS`
- `/dev/apple_mfi` is absent
- no `apple_mfi` modules are loaded
- device tree still contains `spotify_mfi_i2c_pins`

Meaning:

- the inherited boot contract still knows about the MFi hardware wiring
- but the current rootfs does not bring up the userspace or device-node path
  required by the legacy iAP2 stack

Preserved active source of truth for the old stack:

- `reference/legacy-mfi-iap2/slot_a/iap2_agent_new.c`
- `reference/legacy-mfi-iap2/device_root/etc/udev/rules.d/97-mfi.rules`
- `reference/legacy-mfi-iap2/device_root/bin/add-mfi-dev`
- `reference/legacy-mfi-iap2/device_root/bin/remove-mfi-dev`
- `reference/legacy-mfi-iap2/docs/MFI_IAP2_SPECIFICATION.md`

What has been promoted from archaeology into the active tree:

- `buildroot-external/package/carthing-iap2-agent/`

Why this is isolated:

- the current BLE baseline is known-good and should not be contaminated
- the MFi/iAP2 path requires a second target profile with:
  - `bluez5_utils`
  - `dbus`
  - `glib2`
  - restored `apple_mfi` device path

Next concrete steps:

1. Recover the actual `apple_mfi` kernel module artifacts or an equivalent
   inherited rootfs source that already contained them.
2. Create a second Buildroot target profile for the MFi/iAP2 stack instead of
   mutating the current BLE-only baseline.
3. Stage the legacy `/dev/apple_mfi` helpers and udev rule into that second
   profile.
4. Build and deploy `carthing-iap2-agent` there for first live `RegisterProfile`
   and RFCOMM validation.
