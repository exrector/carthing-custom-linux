# Car Thing Custom Linux

This repository replaces the upstream userspace contract for Superbird with an explicit, minimal contract that we control.

Current project stage:

- this is already a custom Linux system in the practical sense
- at this stage "custom Linux" means our own Buildroot rootfs and userspace
- the inherited Superbird bootloader, kernel, dtb, and boot ABI are still reused on purpose
- replacing kernel or dtb is a later decision, not the current migration step

Scope:

- keep the existing Superbird boot contract and hardware BSP assumptions
- remove the hidden upstream userspace policy layer
- replace it with a small rootfs overlay, our own init scripts, and a documented runtime contract

## First Rule On This Mac

When device `№1` is reconnected in normal boot, DO NOT wait for macOS to fix
USB networking by itself.

On this host, the first recovery action is:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

Reason:

- `NCM Gadget` may already be present in `ioreg`
- `en14` may still be `inactive`
- route `172.16.42.0/24` may drift to `utun*`
- that state is host-side drift, not proof that the target disappeared

Only after forced host-side bring-up should device absence or target-side boot
failure be considered.

## Read Order

1. `docs/upstream-userspace-contract.md`
2. `docs/migration-roadmap.md`
3. `docs/buildroot-bringup.md`
4. `docs/macos-device-diagnostics.md`
5. `docs/early-userspace-findings-2026-05-11.md`
6. `docs/storage-map-and-cleanup.md`
7. `docs/reverse-control-agent.md`
8. `docs/local-access-profile.md`
9. `docs/checkpoint-2026-05-18-hid-pair-cold-boot.md`
10. `docs/device1-v1-working-baseline-2026-05-18.md`
11. `docs/device1-reliability-pass-2026-05-18.md`
12. `docs/session-freeze-2026-05-12.md`
13. `docs/factory-identity-2026-05-22.md`
14. `overlay/etc/default/carthing`
15. `overlay/etc/init.d/`
16. `overlay/usr/libexec/carthing/contract-selftest`

## What This Repository Contains

- `docs/`
  - upstream-only contract analysis
  - migration plan from the inherited userspace to our own userspace
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
- `scripts/check-device1-normal-boot-macos.sh`
  - canonical macOS normal-boot diagnostic for `NCM Gadget`, BSD interface mapping, link state, route, and ICMP
- `scripts/bring-up-device1-normal-boot-macos.sh`
  - canonical macOS host-side remediation to assign `172.16.42.1/24` and pin `172.16.42.0/24` back to the NCM interface
- `scripts/install-gnu-patch.sh`
  - installs a project-local GNU `patch` into `host-tools/` for Buildroot on macOS
- `scripts/install-buildroot-host-tools.sh`
  - installs project-local Buildroot host prerequisites into `host-tools/`
- `scripts/reverse-control-server.py`
  - host-side reverse control server for device-driven polling and result return
- `scripts/reverse-agent-enqueue.sh`
  - queues one shell command for the reverse control agent
- `scripts/reset-reverse-control-state.sh`
  - archives stale `pending/` and `running/` reverse-control entries for one device
- `scripts/check-device1-local-open-access-macos.sh`
  - host-side one-shot check for `ssh`, `httpd`, and `telnetd`

## Current Design Choice

The first replacement contract does not depend on `systemd`, `bluetoothd`, or `bluez5_utils` in the target image.

The Bluetooth bring-up path is now explicitly ours:

1. stage Broadcom firmware files
2. reset the Bluetooth chip on GPIO 493
3. attach the Broadcom UART controller with `carthing-btattach-mini`
4. let the kernel create `hci0`
5. expose a real BLE HID pairing profile for iPhone
6. then start the AMS runtime on Bumble `hci-socket:0`

`carthing-bt-fwload` is still kept in the image as a low-level diagnostic and
recovery tool, but it is no longer the preferred runtime path.

This keeps the upstream hardware expectations but removes the upstream Bluetooth policy stack from the target system.

## Immediate Goal

Boot a minimal Linux rootfs on device `№1` that:

- provides `/bin/init`
- configures `usb0`
- gives us at least one reliable control ingress
- stages Bluetooth firmware
- initializes the Bluetooth chip with our own attach path
- starts the Car Thing runtime without `/opt` hacks or manual post-boot steps

In other words: first own userspace completely, then decide whether a kernel replacement is even needed.

## Current Status

- upstream userspace contract mapped into explicit replacement scripts
- first `br2-external` tree created
- custom `carthing-bt-fwload` helper added to avoid `bluez` in the target image
- custom `carthing-btattach-mini` helper added to keep the runtime attach path small and explicit
- `carthing_superbird_rootfs_defconfig` validated against Buildroot `2026.02.1`
- flash bundle generation is scripted to preserve the existing `bootfs.bin` + `env.txt` contract
- attach -> `hci0` -> Bumble `hci-socket:0` is now live-proven on device `№1`
- runtime is now configured to autostart with writable `/run/carthing` logs and persistent bond storage on `mmcblk0p1`
- iPhone pairing requires the HID profile layer first; AMS alone is not sufficient for discovery in iOS Settings
- a real cold boot with the permanent flashed image is now proven:
  - the iPhone pair survives reboot
  - the device auto-reconnects
  - Podcast metadata appears on screen
  - the encoder works
- macOS host diagnostics are now documented around `ioreg` first, not `adb` or raw `ping`
- macOS host bring-up is now scripted separately from diagnostics so `en14` and `172.16.42.0/24` can be recovered consistently
- stale macOS host-routes to `172.16.42.77` are now treated as a first-class failure mode and are cleared by the canonical bring-up script
- user-visible Bluetooth/system identity is now factory efuse-derived:
  - `/sys/class/efuse/usid=8559RP88Q917` -> `Car Thing (SN: Q917)`
  - commit `98d6a85`
- duplicate runtime scaffolding was pruned in commit `c553c3c`
- persistent 512M rootfs: `artifacts/flash-device1-factory-name-20260522/rootfs.img`
  - current sha256: `9fa4dc25db82680e4378288021909b378c893b8eab3ec7a5e3d95d59e4000dba`
- current early-userspace findings are locked in `docs/early-userspace-findings-2026-05-11.md`
- storage and cleanup map is documented in `docs/storage-map-and-cleanup.md`
- legacy MFi / iAP2 notes have been curated into `reference/legacy-mfi-iap2/`
- default local-open ingress is intentional:
  - SSH enabled
  - BusyBox `httpd` on `8080` enabled
  - BusyBox `telnetd` on `2323` enabled
  - default root password is `carthing`
  - canonical access profile documented in `docs/local-access-profile.md`
- the current known-good release artifact is:
  - `artifacts/releases/device1-v1-working-20260518/bundle/`

## Not In Scope Yet

- replacing the bootloader
- replacing the current kernel and dtb
- rewriting the BLE stack from scratch
- touching the working device `№2`
