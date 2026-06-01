# Refactor / consolidation plan — product BT runtime (2026-05-22)

## Superseded Architecture Note — 2026-06-01

This document is still useful as history for identity, rootfs, launch hygiene,
and early A2DP relay decisions. Its product-level mode model is superseded by
`docs/route-graph-architecture-2026-06-01.md`.

Do not continue the old split of persistent trusted devices into hard
`Sources` and `Speakers` sections as the final architecture. The accepted model
is now:

- one trusted-device registry;
- capabilities/endpoints/constraints discovered during enrollment;
- Inputs and Outputs as GUI filters over one registry;
- Audio Hijack-like sessions and route graphs instead of hard runtime modes;
- Remote/Transfer/Mac as presets or saved sessions, not separate Bluetooth
  personas or separate process trees.

The architecture is sound; what's "patchy" is the **delivery / dev scaffolding**,
not the design. This plan turns the scaffolding into a solid base. Do this
*before* shipping, ideally before piling more features on.

## Principle

Separate two things that currently look mixed:
- **Architecture** (keep): one factory identity from manufacture efuse USID; one `Device`
  with all profiles; A2DP AAC passthrough relay; on-request visibility; modular
  GUI. These are root-cause solutions.
- **Scaffolding** (replace): how we run/deploy/patch the device *right now* for
  fast iteration on live hardware.

## Scaffolding to remove

### 1. Runtime location & launch (the big one)
- **Now:** code runs from `/run/product-os` (tmpfs — gone on reboot); launched
  by hand via `nohup` (orphaned, PPid=1); restarted by a script that scrapes env
  from `/proc/<pid>/environ`.
- **Target:** code lives in the **rootfs image** (`overlay/usr/lib/carthing`,
  which is already the repo source); started by the existing `S50-carthing-remote`
  init unit; one launcher, no manual nohup. Drop `/run/product-os` as a runtime
  path (it was only an iteration shortcut).

### 2. Hostname / identity — factory efuse is the source of truth
- **Now:** fixed in commit `98d6a85`. `S04-hostname` and `runtime_paths.device_name()`
  derive the visible identity from `/sys/class/efuse/usid`, e.g.
  `8559RP88Q917` -> `Car Thing (SN: Q917)`.
- **Target:** keep this. The controller MAC is only a technical address and
  last-resort fallback; it is not the normal user-visible identity.

### 3. Config hygiene
- **Now:** `CARTHING_BD_ADDRESS=30:E3:D6:00:5F:A4` may still exist as controller
  configuration input.
- **Target:** do not use that variable for user-visible naming. Naming derives
  from manufacture efuse first, then explicit config/hostname/MAC fallback.

### 4. rootfs is read-only
- **Now:** prompt drop-in was written via `mount -o remount,rw /`.
- **Target:** `etc/profile.d/carthing-prompt.sh` ships in the image (already in
  overlay) — no remount hack. Persistent state stays on `/run/carthing-state`
  (vfat). No ad-hoc rootfs edits.

## Architecture still to build (sound, do on the clean base)

### 5. On-request visibility (pp. 2-3)
Bind `pairing_mode` ↔ real BT. Outside pairing: connectable but **not
discoverable** (bonded/directed advertising — sticks to the paired iPhone),
classic `set_discoverable(False)`. In pairing mode: general discoverable (BLE,
for sources) **and** classic discoverable + speaker inquiry scan (for transfer
targets). Remove the unconditional `start_advertising` + `enable_classic_visibility`
from startup.

### 6. Mode switching (p. 5)
Incoming A2DP (iPhone picks Car Thing as audio output) already flips to the
Transfer desktop. Add a **system pause of the Media-Remote service** while
`transfer_active`, and resume when the source disconnects.

### 7. Settings (p. 6)
`role` (source/speaker) groundwork exists. Split "Trusted devices" into two hard
sections — **Sources** (BLE/AMS) and **Speakers** (A2DP out). Adding each type
happens in pairing mode (see #5).

## Suggested order

1. **Consolidate the base first**: #1 (image + S50 launch), #2 (init hostname),
   #3 (config), #4 (no remount). Cheaper than moving more code later.
2. Then build #5 → #6 → #7 on the clean base.

## Done already (sound, kept)

- **Identity update**: commit `98d6a85` supersedes the older MAC-derived identity.
  The single visible name is manufacture efuse USID -> `Car Thing (SN: Q917)`,
  verified after flashing a persistent 512M rootfs image. See
  `docs/factory-identity-2026-05-22.md`.
