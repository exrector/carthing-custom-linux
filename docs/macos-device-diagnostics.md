# macOS Device Diagnostics

## STOP USING THE WRONG SIGNALS

## FIRST RULE ON THIS MAC

If device `№1` was replugged in normal boot and `NCM Gadget` exists in
`ioreg`, do not wait for `en14` or routing to repair themselves.

Do this first:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

This is not an optional cleanup step. On this host it is the canonical first
recovery action after reconnect.

DO NOT use `adb devices` as the source of truth for device `№1` normal boot.

DO NOT infer "USB gadget absent" from:

- failed `ping`
- a route that currently points at `utun*`
- a stale assumption that the gadget must already be active on `en14`

On this Mac, the canonical normal-boot truth source is the IORegistry:

```sh
./scripts/check-device1-normal-boot-macos.sh
```

That script reads:

1. `ioreg` for `NCM Gadget` presence
2. `ioreg` again for the attached BSD interface name, e.g. `en14`
3. `ifconfig <bsd>` for link state and IP
4. `route get` and `ping` only after the gadget and BSD interface are confirmed

If the gadget exists but host-side link or routing still come up wrong, the
canonical remediation is:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

That script is intentionally separate from the read-only diagnostic. It assigns
`172.16.42.1/24` to the detected NCM interface, clears stale ARP entries for
the target IPs, deletes stale host-routes for `.2` and `.77`, and pins
`172.16.42.0/24` back to the USB interface instead of letting VPN or Wi-Fi
routes win.

## NORMAL BOOT: WHAT COUNTS AS PROOF

The device display is not a reliable mode indicator during recovery. Do not
classify the board from the old visual distinction between `1+4`, `4`, splash,
or no splash. Classify the USB layer with direct probes first.

These states mean different things and must not be collapsed together:

- `NCM Gadget` absent in `ioreg`
  - the USB gadget is missing or re-enumerating
- `NCM Gadget` present and `BSD Name` exists, but `ifconfig status: inactive`
  - the USB gadget exists and macOS attached the NCM driver
  - the host-side USB service still needs explicit bring-up on this Mac
  - do not wait for it to recover by itself
  - run `./scripts/bring-up-device1-normal-boot-macos.sh` before concluding that the target is dead
- `NCM Gadget` present, `BSD Name` exists, link is active, but route points to `utun*`
  - the gadget exists
  - routing is wrong
  - do not wait for VPN routing to move away by itself
  - run `./scripts/bring-up-device1-normal-boot-macos.sh`
- `NCM Gadget` present, link is active, subnet route is pinned to `en14`, but a stale host-route to `.77` still points elsewhere
  - this is still host-side routing drift on macOS
  - delete the stale host-route before concluding that the device vanished
  - the canonical bring-up script now does this automatically
- `NCM Gadget` present, link active, route correct, but no ICMP reply
  - host-side USB/NCM exists
  - target-side service or IP state is still broken
- `NCM Gadget` present, host-side bring-up completed, route is correct, and `tcpdump -ni <bsd>` still sees zero packets
  - treat this as a target-side early boot / no-L3-traffic problem
  - do not misreport it as missing USB hardware

## BURN MODE: WHAT COUNTS AS PROOF

DO NOT use `adb devices` as the source of truth for Burn Mode either.
DO NOT use a single `system_profiler` miss or a missing `NCM Gadget` line as
proof that the device is absent. For recovery flashing, call
`superbird_device.find_device()` and distinguish `usb`, `usb-burn`, `normal`,
and `not-found`.

`scripts/flash-device1-rootfs-only.py` talks to the Amlogic burn device over direct USB via `pyusb`.

That means:

- `adb devices` may be empty while Burn Mode USB access still works
- the flash script itself is the authoritative Burn Mode probe in this repo

## MANUAL EQUIVALENTS

If you need to inspect manually, use these exact classes of tools:

```sh
ioreg -r -n 'NCM Gadget' -w 0 -l
ifconfig en14
route get 172.16.42.2
ping -c 1 172.16.42.77
ping -c 1 172.16.42.2
```

But the preferred path is still the wrapper script because it keeps the interpretation consistent.

If you need the manual host-side remediation equivalent, this is the exact class
of action that `bring-up-device1-normal-boot-macos.sh` performs:

```sh
sudo ifconfig en14 172.16.42.1 netmask 255.255.255.0 up
sudo route -n delete -host 172.16.42.77 || true
sudo route -n delete -net 172.16.42.0/24 || true
sudo route -n add -net 172.16.42.0/24 -interface en14
```
