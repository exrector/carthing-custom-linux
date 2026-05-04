# Migration Roadmap

This roadmap is for replacing the upstream userspace contract with our own contract.

Target device for all risky work:

- device `№1`

Protected device:

- device `№2`

## Phase 0. Freeze The Contract

Deliverables:

- `docs/upstream-userspace-contract.md`
- first rootfs overlay

Exit criteria:

- every upstream userspace dependency is mapped to our replacement

## Phase 1. Boot A Minimal Custom Rootfs

Goal:

- boot a non-NixOS rootfs while keeping the current boot ABI and current kernel/dtb

Required outcomes:

- `/bin/init` works
- shell works
- `usb0` comes up
- SSH works

Do not attempt yet:

- remote autostart
- Bluetooth app runtime

## Phase 2. Recreate Hardware Bring-Up

Goal:

- replace firmware staging, BT reset, BT firmware upload, and metadata setup with our own scripts

Required outcomes:

- `/lib/firmware/brcm` is populated
- GPIO 493 reset works
- `carthing-bt-fwload` one-shot bring-up works
- `/var/lib/bluetooth` metadata path exists

Important note:

- no `bluetoothd`
- no `bluez5_utils` in the target image
- no manual post-boot kill step

## Phase 3. Recreate Access and Input Contract

Goal:

- restore device access and input discoverability using our own scripts

Required outcomes:

- SSH survives reboot
- `usb0` is predictable
- input symlinks exist under `/run/carthing`

## Phase 4. Start The App

Goal:

- start the Car Thing runtime directly from the custom rootfs

Required outcomes:

- app starts without `/opt` mutation
- app has access to Python deps and key store
- screen works
- buttons work
- encoder works
- iPhone reconnects

## Phase 5. Remove Transitional Dependencies

Transitional dependency examples:

- legacy path assumptions
- old runtime layout

This phase should happen only after Phase 4 is stable.

## Stop Conditions

Stop immediately if:

- boot ABI changes are required unexpectedly
- kernel/dtb break basic devices
- UART Bluetooth attach stops working
- recovery access is lost on `№1`

## Success Definition

Success is not "new Linux boots".

Success is:

- custom rootfs
- explicit startup contract
- no systemd or NixOS policy
- no manual BlueZ handoff
- same user-visible behavior as working `№2`
