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
- `№1` now answers on the target IP in normal boot:
  - `172.16.42.2` responds to ICMP
  - ARP resolves to a real device MAC on `en14`
  - this is the first confirmed successful stage-2 network bring-up on the custom rootfs
- The rebuilt rootfs no longer contains stale init duplicates:
  - removed `S30-usbnet`
  - removed `S40-ssh`
  - removed `S40network`
  - removed `S50dropbear`
- `/bin/init` is now a controlled wrapper, not a BusyBox symlink:
  - wrapper runs `S05-usbnet`, `S06-ssh`, and `S07-debug-http` before BusyBox init
  - wrapper keeps retrying early network/ssh in the background
  - this gives us a stage-2 proof path even if normal init later breaks
- `/init` now points to the same wrapper path as `/bin/init`:
  - old stage-1 defaults to `/init`
  - if `init=/bin/init` from kernel cmdline is not honored, stage-2 still lands in our wrapper
- The current rootfs now covers both stage-2 entrypoints explicitly:
  - `/init` -> `init-wrapper`
  - `/bin/init` -> `init-wrapper`
  - this removes a hidden dependency on kernel cmdline handoff correctness
- Early stage-2 now self-mounts the minimum runtime filesystem set:
  - `devtmpfs` on `/dev`
  - `proc` on `/proc`
  - `sysfs` on `/sys`
  - `tmpfs` on `/run`
  - this removes reliance on later init stages before network probing starts
- USB interface probing no longer depends only on `/sys/class/net`:
  - it also falls back to `/proc/net/dev`
  - and it configures candidates through both `ip` and `ifconfig`
- The image now carries host beacon breadcrumbs:
  - boot-time events are emitted toward `http://172.16.42.1:8099`
  - `S05-usbnet` now emits a second beacon when the interface appears late during background retry
  - this removes the earlier blind spot where stage-2 networking could come up after the first failed beacon window

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
- Try to obtain SSH before `rcS` becomes a dependency.
- Continue flashing only `rootfs.img` until SSH on `№1` is stable.

## Current Unknown

- We still do not have SSH into `№1`.
- `172.16.42.2` is alive, but `22/tcp` currently returns `Connection refused`.
- `8080/tcp` also remains closed on the currently flashed image.
- No host beacon has been observed yet from the current boot path.
- That narrows the next unknown down to ssh bring-up only:
  - either `dropbear` never starts
  - or it exits immediately during early boot
  - or the expected stage-2 debug path is still not being entered where we think it is

## Latest Working Theory

- The next suspect is no longer host routing.
- The next suspect is no longer basic stage-2 networking.
- The next suspect is early ssh daemon startup under the cleaned init set.
- The next image being tested carries:
  - widened USB interface matching (`usb*`, `eth*`, `en*`, `ncm*`, `rndis*`)
  - `/proc/net/dev` fallback when `/sys/class/net` is not usable yet
  - early mounts for `/dev`, `/proc`, `/sys`, `/run`
  - `devpts` mounted explicitly in early stage-2
  - background USB interface retries
  - early `S05-usbnet` and `S06-ssh`
  - no duplicate late network/dropbear scripts
  - a wrapper `/bin/init` that tries network+ssh before BusyBox init
  - a matching fallback `/init` for stage-2 handoff compatibility
  - baked host keys in `/etc/dropbear`
  - no runtime dropbear key generation
  - late USB beacon breadcrumbs for the delayed-interface path
  - a pending BusyBox `httpd` path that still needs one more host-side fix before it is guaranteed to land in the target image

## Next Checkpoint Goal

- Get one successful SSH login into `№1` after normal boot.
- As soon as that happens, stop and record:
  - interface names
  - `ip addr`
  - running processes
  - init logs
