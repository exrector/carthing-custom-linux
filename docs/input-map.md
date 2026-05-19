# Car Thing — Input Devices Map

Captured live on device №1 (firmware `device1-v1-working-20260518`) using
`tools/key_probe.py`. This file is the canonical reference for any
input-handling code.

## /dev/input/event0 — `gpio-keys`

Physical buttons. All events are `EV_KEY` with `value=1` (DOWN) or
`value=0` (UP). No autorepeat observed on a short single press.

| Physical button     | code | Linux name    | Notes                       |
| ------------------- | ---- | ------------- | --------------------------- |
| Preset 1            | 2    | `KEY_1`       | Top row, leftmost           |
| Preset 2            | 3    | `KEY_2`       | Top row                     |
| Preset 3            | 4    | `KEY_3`       | Top row                     |
| Preset 4            | 5    | `KEY_4`       | Top row                     |
| Settings            | 50   | *(custom)*    | Top row, rightmost          |
| Back                | 1    | `KEY_ESC`     | Below the encoder           |
| Encoder press       | 28   | `KEY_ENTER`   | Pushing the rotary inward   |

Code 50 has no canonical Linux name (it overlaps `KEY_M` in
input-event-codes.h, but that's coincidental — the gpio-keys driver was
configured with this value for the Settings button). Treat it as a
device-specific code.

## /dev/input/event1 — `rotary@0`

Rotary encoder rotation. Single characteristic:

| Event   | code               | value |
| ------- | ------------------ | ----- |
| `EV_REL` | `REL_HWHEEL` (6)  | `+1` per detent clockwise, `-1` counter-clockwise |

Observed cadence: ~120–230 ms between detents on a steady twist.
No acceleration, no fractional values.

## /dev/input/event2 — `aml_vkeypad`

Amlogic virtual keypad. Reports `KEY_POWER` (116). Not a physical
button — this is a software-driven event from the SoC, currently
unused.

## /dev/input/event3 — `tlsc6x_dbg`

Touchscreen controller (TouchLink TLSC6x). Multi-Touch Protocol B.

### Supported axes (from EVIOCGABS)

| Axis                 | range   | notes |
| -------------------- | ------- | ----- |
| `ABS_MT_SLOT`        | 0..1    | **max 2 simultaneous contacts** (hardware limit) |
| `ABS_MT_POSITION_X`  | 0..480  | matches display width 1:1 |
| `ABS_MT_POSITION_Y`  | 0..800  | matches display height 1:1 |
| `ABS_MT_PRESSURE`    | 0..127  | **always reports 13** — driver constant, do not use |
| `ABS_MT_TOUCH_MAJOR` | 0..15   | contact patch size |
| `ABS_MT_TRACKING_ID` | 0..65535 | unique id per contact, `-1` on lift |

`BTN_TOUCH` is emitted on first contact down / last contact up.

### Captured behaviour — 2026-05-19

| Gesture           | Duration | Sampling | Notes |
| ----------------- | -------- | -------- | ----- |
| Single tap        | ~55 ms   | DOWN + 1 snapshot + UP | new tracking id each tap |
| Double tap        | 35 + 35 ms, ~220 ms gap | as above ×2 | adjacent tracking ids |
| Long press        | 2438 ms  | DOWN + 1 snapshot + UP — **no intermediate samples while finger stays still** | implement long-press as a wall-clock timer from DOWN |
| Two-finger tap    | 330 ms   | both slots active concurrently with different tracking ids | second finger arrives 13 ms after first |
| Vertical swipe    | ~1.0 s   | ~12 ms between snapshots → **~83 Hz** | smooth, ±1 px noise |
| Horizontal swipe  | ~1.0 s   | same cadence | smooth |
| Pinch (open)      | ~1.5 s   | both slots track independently, diverging | works as expected |

### Observed driver behaviour

- `ABS_MT_PRESSURE` reports the constant value 13 in every sample.
- A stationary finger emits one `SYN_REPORT` at touch-down and nothing
  more until lift.
- Coordinates are emitted in panel orientation (480 wide × 800 tall),
  matching `ABS_MT_POSITION_X`/`Y` ranges.

---

## Capture log — 2026-05-19

Source: `/run/keys.log` on device, monitor mode.

```
10:28:53.571  KEY_1(2)        DOWN     ← Preset 1
10:28:53.879  KEY_1(2)        UP
10:28:55.419  KEY_2(3)        DOWN     ← Preset 2
10:28:55.727  KEY_2(3)        UP
10:28:56.343  KEY_3(4)        DOWN     ← Preset 3
10:28:56.607  KEY_3(4)        UP
10:28:57.619  KEY_4(5)        DOWN     ← Preset 4
10:28:57.927  KEY_4(5)        UP
10:28:59.423  UNKNOWN(50)     DOWN     ← Settings
10:28:59.819  UNKNOWN(50)     UP
10:29:03.339  KEY_ESC(1)      DOWN     ← Back
10:29:03.647  KEY_ESC(1)      UP
10:29:07.563  KEY_ENTER(28)   DOWN     ← Encoder press
10:29:08.003  KEY_ENTER(28)   UP
10:29:11.106  REL_HWHEEL(6)   +1       ← Encoder right (7 detents)
...
10:29:14.852  REL_HWHEEL(6)   -1       ← Encoder left (7 detents)
...
```
