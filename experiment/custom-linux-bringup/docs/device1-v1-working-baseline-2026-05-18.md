# Device1 V1 Working Baseline 2026-05-18

This is the first baseline that is proven end-to-end after a real cold boot on
device `№1`.

## What This Baseline Guarantees

- inherited `bootfs.bin`, `env.txt`, bootloader, kernel, and dtb stay unchanged
- only `rootfs.img` is replaced
- local-open ingress works:
  - `ssh`
  - password fallback
  - `httpd`
  - `telnetd`
  - `reverse-agent`
- Bluetooth runtime works through the kernel attach path:
  - firmware stage
  - `carthing-btattach-mini`
  - kernel `hci0`
  - HID pairing identity for iPhone discovery
  - AMS runtime on Bumble `hci-socket:0`
- bond keys persist across reboot on `mmcblk0p1`

## Proven Live After Cold Boot

- the already paired iPhone reconnects automatically
- the device GUI returns without manual intervention
- Podcast metadata appears on screen
- the encoder works
- USB ingress can still be recovered on macOS after normal boot

## Known Open Reliability Gap

- the device does not yet "stick" to the iPhone across every Bluetooth toggle
  scenario
- this is a reconnect-policy problem, not a cold-boot pairing problem
- if the user presses `Forget This Device` on iPhone, the device-side
  `keys.json` must also be cleared before expecting a clean new pair

## Canonical Artifact

- bundle directory:
  - `artifacts/releases/device1-v1-working-20260518/bundle/`
- active working rootfs:
  - `artifacts/flash-device1-attach/rootfs.img`
- current rootfs SHA-256:
  - `8f2e84cdc22a750098f87598255ba5f77c1d8d0b9f8e671535aefdca0129dcdd`

## Canonical Commits

The baseline is anchored by this commit chain:

- `0103346` `Checkpoint prepare attach autostart rootfs`
- `5021eb3` `Checkpoint move bt runtime autostart into init-wrapper`
- `eb649e8` `Checkpoint persist HID pairing path and bond storage`
- `0bfec2a` `Checkpoint prove cold boot and fix stale USB host route`

## What Is Still Intentionally Old

- bootloader
- kernel
- dtb
- the underlying Broadcom firmware blob
- the overall Superbird boot ABI

This is intentional. At this stage the project goal is a custom Linux
userspace, not a full boot-chain replacement.
