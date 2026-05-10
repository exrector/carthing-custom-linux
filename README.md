# Car Thing Custom Linux

This repository replaces the upstream userspace contract for Superbird with an explicit, minimal contract that we control.

Scope:

- keep the existing Superbird boot contract and hardware BSP assumptions
- remove the hidden NixOS/systemd/BlueZ policy layer
- replace it with a small rootfs overlay, our own init scripts, and a documented runtime contract

This repository is intentionally not based on the local `carthing-nixos` or `carthing-media-remote` project copies. Those can help explain history, but the architecture work here is driven by upstream behavior and by the live hardware contract.

## Read Order

1. `docs/upstream-userspace-contract.md`
2. `docs/migration-roadmap.md`
3. `docs/buildroot-bringup.md`
4. `docs/storage-map-and-cleanup.md`
5. `docs/reverse-control-agent.md`
6. `overlay/etc/default/carthing`
7. `overlay/etc/init.d/`
8. `overlay/usr/libexec/carthing/contract-selftest`

## What This Repository Contains

- `docs/`
  - upstream-only contract analysis
  - migration plan from NixOS userspace to our own userspace
- `reference/legacy-mfi-iap2/`
  - curated archive of the old MFi / iAP2 reverse-engineering notes and one representative `slot_a` code snapshot
  - preserved so the large legacy Car Thing trees can be deleted without losing the useful archaeology

- `buildroot-external/`
  - first Buildroot `br2-external` tree for the custom rootfs
  - custom packages owned by this repository
  - target defconfig that intentionally excludes `bluez`
  - Buildroot package patches needed for macOS host builds

- `overlay/`
  - generic rootfs overlay for a minimal Linux system
  - BusyBox-init style startup scripts
  - optional udev rules
  - helper scripts for Bluetooth, USB networking, input discovery, and runtime startup

- `scripts/install-overlay.sh`
  - copies the overlay into a target rootfs for testing
- `scripts/configure-buildroot.sh`
  - points a Buildroot checkout at this repository's `br2-external` tree
- `scripts/build-rootfs.sh`
  - configures and builds the first custom rootfs image
- `scripts/verify-target-rootfs.sh`
  - checks the built target rootfs for required runtime files and rejects `bluez`/`systemd`
- `scripts/prepare-flash-bundle.sh`
  - reuses the known-good Superbird `flash/` contract and replaces only `rootfs.img`
- `scripts/install-gnu-patch.sh`
  - installs a project-local GNU `patch` into `host-tools/` for Buildroot on macOS
- `scripts/install-buildroot-host-tools.sh`
  - installs project-local Buildroot host prerequisites into `host-tools/`
- `scripts/reverse-control-server.py`
  - host-side reverse control server for device-driven polling and result return
- `scripts/reverse-agent-enqueue.sh`
  - queues one shell command for the reverse control agent

## Current Design Choice

The first replacement contract does not depend on `systemd`, `bluetoothd`, or `bluez5_utils` in the target image.

The Bluetooth bring-up path is now explicitly ours:

1. stage Broadcom firmware files
2. reset the Bluetooth chip on GPIO 493
3. run `carthing-bt-fwload` once to upload firmware and release the UART
4. start the app directly on `/dev/ttyS1`

This keeps the upstream hardware expectations but removes the upstream Bluetooth policy stack from the target system.

## Immediate Goal

Boot a minimal Linux rootfs on device `№1` that:

- provides `/bin/init`
- configures `usb0`
- gives us at least one reliable control ingress
- stages Bluetooth firmware
- initializes the Bluetooth chip with our own loader
- starts the Car Thing runtime without `/opt` hacks or manual post-boot steps

## Current Status

- upstream userspace contract mapped into explicit replacement scripts
- first `br2-external` tree created
- custom `carthing-bt-fwload` helper added to avoid `bluez` in the target image
- `carthing_superbird_rootfs_defconfig` validated against Buildroot `2026.02.1`
- flash bundle generation is scripted to preserve the existing `bootfs.bin` + `env.txt` contract
- reverse control agent is now wired into early init for the next `№1` test
- storage and cleanup map is documented in `docs/storage-map-and-cleanup.md`
- legacy MFi / iAP2 notes have been curated into `reference/legacy-mfi-iap2/`

## Not In Scope Yet

- replacing the bootloader
- replacing the current kernel and dtb
- rewriting the BLE stack from scratch
- touching the working device `№2`
