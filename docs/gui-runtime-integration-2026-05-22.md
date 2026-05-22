# GUI runtime integration — gotchas & recipes (2026-05-22)

Companion notes for commit `e40d940` (*feat(ui): wire the modular Compositor
into the live runtime*). The commit message covers the architecture; this file
records the sharp edges that are easy to forget.

## Architecture recap

- `media_remote.py` builds the modular `Compositor` over `DRMDisplayAdapter`.
  The old single-screen fallback was removed during cleanup; if GUI import or
  DRM setup fails, the runtime continues headless with AMS/input recovery.
- Data flow: AMS `MediaState` → `_sync_media_to_appstate` → `AppState.iphone` →
  `compositor.broadcast_state`. UI intents → `Dispatcher` → `_ble_command` →
  `ams.send_command`.
- Input: `input_handler.start(on_event=compositor.handle_input)`. The old
  direct-to-AMS path stays as the fallback when no GUI sink is wired.

## Code-level nuances (also in inline comments)

- **play/pause both map to `CMD_TOGGLE`** — AMS has no discrete play/pause.
  The UI's `playing` flag is re-synced from AMS state updates, so a brief
  mismatch self-corrects.
- **Only the `iphone` source exists on-device.** `Mac` is simulator-only;
  `_ble_command` ignores non-iphone sources.
- **`handle_input` is synchronous and renders in the event loop** (blocking
  DRM blit). Matches the pre-existing render-in-loop pattern; fine at human
  input rates.
- **`input_handler` high-level event names must equal `ui_screen.Input` values**
  (`encoder_cw`, `press`, `btn_1`…). The input layer deliberately avoids
  importing the PIL/GUI stack, so the strings are duplicated, not imported.

## ⚠️ On-device limitation — desktop navigation

Switching desktops (Mac / Settings / Notifications) is **not reachable from the
physical buttons**. Navigation was designed around touchscreen swipes (arrows in
the simulator), but `input_handler` only reads buttons (`event0`) + encoder
(`event1`). The touchscreen (`event2`, ABS multitouch) is not wired. On the
device only the NowPlaying desktop is visible.

**TODO:** read `event2` and emit `Input.TAP` / swipe, or assign a button to
`SWIPE_LEFT/RIGHT`.

## Deploy / restart gotchas (BusyBox target)

- **`scp` fails** — no `sftp-server` on the device. Deploy with tar over ssh:
  `tar -cf - <files> | ssh root@… 'tar -xf - -C /usr/lib/carthing'`.
- **No `pkill`/`pgrep`.** Kill by PID:
  `ps w | grep "[m]edia_remote.py" | awk '{print $1}'`.
- **`OSError [Errno 16] Device or resource busy`** on restart if the old runtime
  still holds `hci-socket:0`. Kill the old process and wait ~2–4 s for the HCI
  socket to free before starting the new one.
- **Clear `/usr/lib/carthing/__pycache__`** on a hot deploy of changed modules.
- Restart: `/etc/init.d/S50-carthing-remote` (nohup → `run-media-remote`).
  Log: `/run/carthing/carthing-remote.log`. Success marker:
  `DRM display ready — modular GUI active`.

## System binding — clean BLE re-pair (post-A2DP)

Symptom: `connections=0 advertising=True`, blank screen. Cause: the keystore held
a classic `link_key` (BR/EDR, from an A2DP experiment); AMS needs a BLE bond.

Recipe:
1. Reset keystore to `{}` (back it up first).
2. On iPhone: *Forget This Device* for "CarThing".
3. Re-pair (Just Works: `sc=True, mitm=False, bonding=True`). The keystore then
   gets `ltk` + `irk`, and AMS streams metadata.

Notes:
- Keystore is **persistent**: `/run/carthing-state/carthing/keys.json` on the
  vfat partition `/dev/mmcblk0p1` (mounted by `S11-runtime-state`). Survives reboot.
- `CARTHING_BT_INIT_BACKEND=attach` (btattach builds `hci0` from `ttyS1`, **no**
  `.hcd` fwload) is a committed pivot (`8d6c279`), not a fault. BLE works.

## Verification (2026-05-22, device #2)

GUI active; after a clean BLE re-pair the iPhone connected (resolvable addr
`6C:62:FE:09:87:AB`), SMP bonded (`ltk`/`irk`), AMS subscribed, and live
metadata rendered ("Пальма-де-Майорка — Шуфутинский Михаил"). No render errors.
