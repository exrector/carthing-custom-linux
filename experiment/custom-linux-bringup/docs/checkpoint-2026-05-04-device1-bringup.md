# Checkpoint 2026-05-04

## Stable Ground

- `Buildroot` rootfs reliably rebuilds on this Mac host.
- Target rootfs verification passes:
  - no `bluez`
  - no `bluetoothd`
  - no `systemd`
  - `/bin/init` exists
- `flash-device1` bundle is reproducibly regenerated from the current rootfs.
- `flash-device1` rootfs can now also be regenerated directly from the current `target/` without a full Buildroot image pass:
  - this is the fallback path when the `carthing-buildroot-case` volume fills up during `rootfs.ext2` generation
  - script: `scripts/build-rootfs-image-fallback.sh`
- `rootfs-only` flashing for device `№1` works reliably in Burn Mode.
- `rootfs-only` flash probing must use direct USB via `pyusb`:
  - `adb devices` is **not** the Burn Mode source of truth in this repo
- Device `№1` now holds `NCM Gadget` steadily in normal boot instead of dropping back into the earlier obvious reboot loop.
- Host-side macOS diagnostics are now separated from target-side failure:
  - `NCM Gadget` appears reliably as `en14`
  - route to `172.16.42.2` can be pinned back to `en14`
  - ARP loopback was observed and cleared explicitly
  - the canonical host-side source of truth is `scripts/check-device1-normal-boot-macos.sh`
  - `ioreg` comes first; `ping` and `route get` are secondary signals
- `№1` now answers on the stage-2 fingerprint IP in normal boot:
  - `172.16.42.77` responds to ICMP
  - `172.16.42.2` no longer responds on the diagnostic image
  - ARP resolves to a real device MAC on `en14`
  - this is the first confirmed proof that our own `S05-usbnet` is the component configuring the live target address
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
- BusyBox emergency ingress is now baked into the image build:
  - `httpd` is present in the target image
  - `telnetd` is present in the target image
  - `S08-debug-telnet` starts a standalone shell listener on `2323`
  - this gives us a stage-2 proof path that does not depend on Python or Dropbear
- The next diagnostic image now carries service progress IP markers:
  - `172.16.42.78` = `S06-ssh` entered
  - `172.16.42.79` = `dropbear` stayed alive after launch
  - `172.16.42.80` = `S07-debug-http` entered
  - `172.16.42.81` = BusyBox `httpd` launch path reached
  - `172.16.42.82` = `S08-debug-telnet` entered
  - `172.16.42.83` = BusyBox `telnetd` launch path reached
  - `172.16.42.84` = `S09-reverse-agent` entered
  - `172.16.42.85` = reverse agent stayed alive after launch
  - `172.16.42.184` = no `python3`
  - `172.16.42.185` = reverse agent exited immediately
  - `172.16.42.188` = reverse agent file missing
  - `172.16.42.176` = host keys missing
  - `172.16.42.179` = `dropbear` exited immediately

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
- `172.16.42.77` is alive, but `22/tcp`, `8080/tcp`, and `2323/tcp` currently return `Connection refused`.
- No host beacon has been observed yet from the current boot path.
- That narrows the next unknown down to service progress after `S05-usbnet`:
  - whether `S06-ssh` is reached at all
  - whether `dropbear` dies immediately after exec
  - whether `S07-debug-http` and `S08-debug-telnet` are entered at all
  - whether `S09-reverse-agent` starts and polls home even if no inbound ports ever open
  - whether the lack of open ports is a daemon failure or a script-order failure

## 2026-05-11 Narrowed Failure

- A later diagnostic image proves the next failure is above basic stage-2 networking:
  - `172.16.42.77` responds
  - `172.16.42.84` responds
  - `172.16.42.189` responds
  - `172.16.42.185` no longer appears on that image
- `.189` is the current strongest localization signal:
  - module-level probe failed before `reverse-agent.py` reached `main()`
- Host-side queue state supports the same conclusion:
  - reverse-agent commands remain in `pending/`
  - no `/agent/poll` or `/agent/result` activity arrives
- Host beacons show repeated `s07-started`, `s08-started`, and `s09-module-probe-failed`
  - this strongly implicates the `init-wrapper` retry loop and top-level Python startup, not the USB or IP layers
- See `docs/early-userspace-findings-2026-05-11.md` for the consolidated Buildroot/BusyBox/Python findings and the cleanup order they imply.

## Later Regression Check

- A later control flash using the preserved Buildroot artifact
  - `/Volumes/carthing-buildroot-case/output-carthing/images/rootfs.ext2`
  - flashed via `artifacts/flash-device1-buildroot-control/rootfs.img`
  - completed cleanly in Burn Mode with `failures=0`
- That control image does **not** currently reproduce the earlier `.77` proof:
  - `NCM Gadget` repeatedly disappears and reappears in normal boot
  - the gadget MAC changes across re-enumerations
  - during the windows where the USB gadget exists, neither `172.16.42.77` nor `172.16.42.2` answers
  - presence of `NCM Gadget` alone is not enough to claim target networking is alive
  - this points to a target-side early boot / USB gadget reset loop, not a macOS route issue

## Latest Working Theory

- The next suspect is no longer host routing.
- The next suspect is no longer basic stage-2 networking.
- The next suspect is service execution after stage-2 network is already alive.
- The next image being tested carries:
  - the `.77` network fingerprint proving `S05-usbnet`
  - per-service debug IP markers for `S06`, `S07`, `S08`, and `S09`
  - a reverse control agent that polls the host and returns stdout/stderr
  - the fallback `rootfs.img` rebuild path from `target/`
  - no restored dependency on `bluez`, `btattach`, or `systemd`

## Next Checkpoint Goal

- Get one successful control foothold into `№1` after normal boot.
- As soon as that happens, stop and record:
  - interface names
  - `ip addr`
  - running processes
  - init logs
