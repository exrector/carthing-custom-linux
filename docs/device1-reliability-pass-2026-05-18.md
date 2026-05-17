# Device1 Reliability Pass 2026-05-18

This checklist is for validating the first known-good baseline without changing
the image again.

## Goal

Prove that the current working state is repeatable and not just a lucky boot.

## Test Matrix

### Cold Boot Repetition

Run `3-5` full cycles:

1. power off device `№1`
2. power on into `normal boot`
3. confirm:
   - iPhone reconnects automatically
   - GUI appears
   - current media metadata appears
   - encoder works

### iPhone Bluetooth Toggle

With the device already booted:

1. turn Bluetooth off on the iPhone
2. wait a few seconds
3. turn Bluetooth back on
4. confirm reconnect without re-pairing

### Phone Reboot

1. leave the device powered on
2. reboot the iPhone
3. confirm reconnect without deleting the pair

### USB Service Check

On the Mac:

1. confirm `NCM Gadget` in `ioreg`
2. run `./scripts/bring-up-device1-normal-boot-macos.sh`
3. confirm:
   - `ssh`
   - `httpd`
   - `telnetd`
   - `reverse-agent`

## Failure Classification

- if Bluetooth pairing is lost after reboot:
  - check `mmcblk0p1` mount and `keys.json`
- if iPhone reconnect fails but pairing still exists:
  - check HID path before AMS path
- if the device works on Bluetooth but Mac cannot reach `172.16.42.77`:
  - check for stale host-route drift on macOS before blaming the device

## Rule

Do not change the image during this pass unless the baseline fails in a clear,
repeatable way.
