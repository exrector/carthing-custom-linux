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

## Findings Locked In

- The previous rootfs was invalid for the reused boot layer because it lacked `/bin/init`.
- The old boot layer is still reused, so boot contract compatibility matters:
  - current boot path expects stage-2 init at `/bin/init`
  - replacing only `rootfs.img` is viable, but only if that contract is preserved
- A single failure in early init scripts was too expensive:
  - `rcS` used to abort the whole boot path on the first failing script
  - this is now softened so later services can still run

## Current Strategy

- Bring network and `ssh` up before Bluetooth bring-up.
- Keep Bluetooth init from being able to block first access.
- Configure candidate USB network interfaces aggressively and retry in background.
- Continue flashing only `rootfs.img` until SSH on `№1` is stable.

## Current Unknown

- We still do not have SSH into `№1`.
- `NCM Gadget` is now stable on the host, but `172.16.42.2` still does not answer.
- That means one of these is still true:
  - stage-2 is not fully reached
  - stage-2 runs, but USB/IP setup still does not happen as expected
  - the gadget interface appears under a path we still do not handle correctly

## Next Checkpoint Goal

- Get one successful SSH login into `№1` after normal boot.
- As soon as that happens, stop and record:
  - interface names
  - `ip addr`
  - running processes
  - init logs
