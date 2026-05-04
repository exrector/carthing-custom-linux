# Checkpoint 2026-05-04

## Stable Ground

- `Buildroot` rootfs reliably rebuilds on this Mac host.
- Target rootfs verification passes:
  - no `bluez`
  - no `bluetoothd`
  - no `systemd`
  - `/bin/init` exists
- `flash-device1` bundle is reproducibly regenerated from the current rootfs.
- `rootfs-only` flashing for device `№1` works reliably in Burn Mode.
- Device `№1` now holds `NCM Gadget` steadily in normal boot instead of dropping back into the earlier obvious reboot loop.
- Host-side macOS diagnostics are now separated from target-side failure:
  - `NCM Gadget` appears reliably as `en14`
  - route to `172.16.42.2` can be pinned back to `en14`
  - ARP loopback was observed and cleared explicitly
- The rebuilt rootfs no longer contains stale init duplicates:
  - removed `S30-usbnet`
  - removed `S40-ssh`
  - removed `S40network`
  - removed `S50dropbear`

## Findings Locked In

- The previous rootfs was invalid for the reused boot layer because it lacked `/bin/init`.
- The old boot layer is still reused, so boot contract compatibility matters:
  - current boot path expects stage-2 init at `/bin/init`
  - replacing only `rootfs.img` is viable, but only if that contract is preserved
- A single failure in early init scripts was too expensive:
  - `rcS` used to abort the whole boot path on the first failing script
  - this is now softened so later services can still run
- The image had been carrying old service policy forward across rebuilds:
  - overlay copy alone was not enough because deleted files stayed alive in `target/`
  - cleanup is now enforced in post-build and overlay install steps

## Current Strategy

- Bring network and `ssh` up before Bluetooth bring-up.
- Keep Bluetooth init from being able to block first access.
- Configure candidate USB network interfaces aggressively and retry in background.
- Keep only one boot-time network path and one SSH path in the image.
- Continue flashing only `rootfs.img` until SSH on `№1` is stable.

## Current Unknown

- We still do not have SSH into `№1`.
- `NCM Gadget` is now stable on the host, but `172.16.42.2` still does not answer.
- That means one of these is still true:
  - stage-2 is not fully reached
  - stage-2 runs, but USB/IP setup still does not happen as expected
  - the gadget interface appears under a path we still do not handle correctly

## Latest Working Theory

- The next suspect is no longer host routing.
- The next suspect is target-side stage-2 behavior under the cleaned init set:
  - either `S05-usbnet` still misses the real interface timing/path
  - or stage-2 still does not run far enough to configure `172.16.42.2`
- The next image being tested carries:
  - widened USB interface matching (`usb*`, `eth*`, `en*`, `ncm*`, `rndis*`)
  - background USB interface retries
  - early `S05-usbnet` and `S06-ssh`
  - no duplicate late network/dropbear scripts

## Next Checkpoint Goal

- Get one successful SSH login into `№1` after normal boot.
- As soon as that happens, stop and record:
  - interface names
  - `ip addr`
  - running processes
  - init logs
