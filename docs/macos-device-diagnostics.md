# macOS Device Diagnostics

## STOP USING THE WRONG SIGNALS

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
the target IPs, and pins `172.16.42.0/24` back to the USB interface instead of
letting VPN or Wi-Fi routes win.

## NORMAL BOOT: WHAT COUNTS AS PROOF

These states mean different things and must not be collapsed together:

- `NCM Gadget` absent in `ioreg`
  - the USB gadget is missing or re-enumerating
- `NCM Gadget` present and `BSD Name` exists, but `ifconfig status: inactive`
  - the USB gadget exists and macOS attached the NCM driver
  - the host-side USB service may still need explicit bring-up on this Mac
  - run `./scripts/bring-up-device1-normal-boot-macos.sh` before concluding that the target is dead
- `NCM Gadget` present, `BSD Name` exists, link is active, but route points to `utun*`
  - the gadget exists
  - routing is wrong
  - run `./scripts/bring-up-device1-normal-boot-macos.sh`
- `NCM Gadget` present, link active, route correct, but no ICMP reply
  - host-side USB/NCM exists
  - target-side service or IP state is still broken
- `NCM Gadget` present, host-side bring-up completed, route is correct, and `tcpdump -ni <bsd>` still sees zero packets
  - treat this as a target-side early boot / no-L3-traffic problem
  - do not misreport it as missing USB hardware

## BURN MODE: WHAT COUNTS AS PROOF

DO NOT use `adb devices` as the source of truth for Burn Mode either.

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
sudo route -n delete -net 172.16.42.0/24 || true
sudo route -n add -net 172.16.42.0/24 -interface en14
```
