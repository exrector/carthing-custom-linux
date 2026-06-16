# Checkpoint 2026-05-18 HID Pair Cold Boot

## What Was Proven Live

After flashing the persistent HID-pairing rootfs and booting `normal boot`,
device `№1` was verified live in the intended user flow:

- the existing iPhone pair survived the reboot
- the device auto-reconnected to the iPhone
- the GUI came up on the display without live overrides
- Podcast metadata appeared on screen
- the encoder worked against the live iPhone session

This proves that the permanent runtime path is now correct:

1. `S11-runtime-state` mounts `mmcblk0p1`
2. bond keys are reused from persistent storage
3. HID pairing identity remains valid after reboot
4. `media_remote.py` starts automatically and reaches AMS/UI state

## What Was Also Verified Over USB

The USB service path still exists after the same cold boot:

- `NCM Gadget` appears in `ioreg`
- host-side `en14` can be brought up to `172.16.42.1/24`
- `ssh` access works again once stale macOS routing is removed
- live device state over USB confirms:
  - `/run/carthing-state/carthing/keys.json` exists
  - `dropbear`, `httpd`, `telnetd`, `reverse-agent`, `carthing-btattach-mini`,
    and `media_remote.py` are running
  - `/sys/class/bluetooth/hci0` exists
  - `reverse-agent.state` is `idle`
  - runtime log shows `connections=1`, `advertising=False`, and successful
    `HB: ping OK`

## Host-Side Caveat On This Mac

The remaining confusion after the successful cold boot was again on macOS, not
on the device.

Two separate routing failures are possible on this host:

- the subnet route `172.16.42.0/24` drifts to `utun*`
- a stale host-route to `172.16.42.77` survives on `en0`, even after the subnet
  route is pinned back to `en14`

That second case is easy to miss because `en14` can already be active while USB
`ssh` still times out. The correct fix is to delete the stale host-route first,
then rely on the `172.16.42.0/24` route on `en14`.

The canonical host-side remediation is now:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

That script now clears stale host-routes to `.2` and `.77` before pinning the
USB subnet route.
