# Refactor / consolidation plan — product BT runtime (2026-05-22)

The architecture is sound; what's "patchy" is the **delivery / dev scaffolding**,
not the design. This plan turns the scaffolding into a solid base. Do this
*before* shipping, ideally before piling more features on.

## Principle

Separate two things that currently look mixed:
- **Architecture** (keep): one unique identity from the real MAC; one `Device`
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

### 2. Hostname / identity — straighten the seam
- **Now:** `sethostname()` is a side-effect inside `ble_transport.init_ble`
  (after `power_on`), so the hostname only exists once the Python runtime is up,
  and the responsibility is smeared into the BT module.
- **Target:** a dedicated init step **after HCI is up** (after `S20-bt-init`)
  reads the real controller BD address (`hciconfig hci0` / `btmgmt info`) and
  sets the hostname. `ble_transport` then only *reads* `device_name()`. Hostname
  becomes independent of the Python runtime; `S04-hostname` stops being a guess.

### 3. Config hygiene
- **Now:** `CARTHING_BD_ADDRESS=30:E3:D6:00:5F:A4` is the *cloned* address of unit
  #1; we work around it by reading the real controller MAC.
- **Target:** drop the static/incorrect BD address (or generate it); identity
  derives only from the real controller. Re-check whether bumble's `Device`
  needs a configured address at all on this controller.

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

- **п.1**: one unique name from the real MAC → hostname + BLE + classic + shell
  prompt (commits `d840c1e`, `bd0d10a`). Verified: `CarThing-30E3D604C342`.
