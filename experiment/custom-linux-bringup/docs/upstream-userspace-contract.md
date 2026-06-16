# Upstream Userspace Contract

This file describes what the upstream Superbird stack expects from Linux userspace.

The goal is to replace this contract with our own implementation, not to pretend it does not exist.

## Source Scope

Primary upstream references:

- `JoeyEamigh/nixos-superbird`
- `bishopdynamics/superbird-tool`

This document does not use local project history as an architectural source of truth.

## Boot Contract

The bootloader-side contract already exists before userspace starts.

Expected boot partition payload:

- `Image`
- `superbird.dtb`
- `initrd`

Expected rootfs contract:

- a valid `/bin/init`

Upstream evidence:

- `modules/boot/bootfs/resources/env.txt`
- `modules/boot/rootfs/default.nix`

Implication:

- we can replace NixOS userspace
- we cannot replace the boot payload format blindly
- the first custom system should keep the current boot ABI intact

## Required Runtime Paths

The current hardware and app stack expects these paths to be meaningful:

- `/bin/init`
- `/dev/ttyS1`
- `/dev/dri/card0`
- `/dev/input/event*`
- `/sys/class/gpio/gpio493`
- `/sys/class/efuse/usid`
- `/sys/class/efuse/mac_bt`
- `/lib/firmware/brcm/BCM.hcd`
- `/lib/firmware/brcm/BCM20703A2.hcd`
- `/var/lib/bluetooth`
- `/etc/machine-info`
- `/etc/superbird`

These are not optional if we want functional parity.

## Upstream Service Dependencies

The upstream userspace contract is currently spread across multiple NixOS modules.

### 1. Firmware staging

Upstream behavior:

- if `/lib/firmware/brcm/BCM.hcd` and `BCM20703A2.hcd` are missing, copy them into `/lib/firmware/brcm`

Upstream source:

- `modules/sys/firmware/default.nix`

Replacement:

- `overlay/etc/init.d/S10-firmware-stage`

### 2. Bluetooth chip reset and attach

Upstream behavior:

- export GPIO 493
- set direction to `out`
- drive reset low then high
- sleep briefly
- run `btattach -P bcm -B /dev/ttyS1`

Upstream source:

- `modules/sys/gpio.nix`

Critical point:

- this is not a kernel-only behavior
- userspace must do it

Replacement:

- `overlay/etc/init.d/S20-bt-init`
- `buildroot-external/package/carthing-bt-fwload/`

### 3. BlueZ metadata and aliasing

Upstream behavior:

- write `/etc/machine-info` with `PRETTY_HOSTNAME`
- create `/var/lib/bluetooth/<mac>/settings`
- set device alias
- write `/etc/superbird`

Upstream source:

- `modules/net/bluetooth.nix`
- `modules/sys/init.nix`

Replacement:

- `overlay/etc/init.d/S25-bt-metadata`

### 4. USB networking

Upstream behavior:

- use `usb0`
- run `dnsmasq`
- serve a tiny DHCP range so the host can get `172.16.42.1`

Upstream source:

- `modules/net/dhcp.nix`

Replacement:

- `overlay/etc/init.d/S30-usbnet`

Design change:

- our first contract defaults to static addressing on the device
- optional DHCP remains possible, but it is not mandatory

### 5. SSH access

Upstream behavior:

- start SSH server
- allow root login
- allow password auth
- install host keys into `/etc/ssh`

Upstream source:

- `modules/net/ssh.nix`

Replacement:

- `overlay/etc/init.d/S40-ssh`

Design change:

- prefer `dropbear` for the first custom userspace
- keep the contract explicit and minimal

### 6. Input handling assumptions

Upstream behavior:

- add udev rules that treat `event0` as gpio keys
- add udev rules that treat `event1` as rotary input

Upstream source:

- `modules/sys/hardware.nix`

Replacement:

- `overlay/etc/init.d/S45-input-links`
- optional `overlay/etc/udev/rules.d/99-carthing-input.rules`

Design change:

- our base contract does not require `udev`
- we create stable symlinks under `/run/carthing/`

## Minimum Binary Set We Must Provide

The first custom contract expects these userland tools:

- `/bin/sh`
- `mount`
- `mkdir`
- `cp`
- `cat`
- `printf`
- `sleep`
- `sed`
- `awk`
- `ip`
- `kill`
- `ln`
- `dropbear` and `dropbearkey` or an equivalent SSH server
- `python3`
- `carthing-bt-fwload` or an equivalent Broadcom UART firmware loader

This is much smaller than a full NixOS or systemd stack, but it is not zero.

## What Is Truly Mandatory

Mandatory to preserve behavior:

- boot ABI
- current kernel/dtb on the first iteration
- Broadcom firmware files
- Bluetooth reset and firmware upload
- UART access on `/dev/ttyS1`
- working DRM device
- working input devices
- some SSH path for recovery

Not mandatory in the same form:

- NixOS
- systemd
- `bluetoothd`
- `bluez5_utils`
- `dnsmasq`
- OpenSSH
- udev naming rules

## Contract Replacement Rule

Every upstream behavior should be replaced in one of three ways:

1. keep exactly as-is because it is part of the boot or kernel ABI
2. reimplement as a small shell script or helper binary we own
3. delete only if the app no longer needs it

Anything else is how systems become un-debuggable again.
