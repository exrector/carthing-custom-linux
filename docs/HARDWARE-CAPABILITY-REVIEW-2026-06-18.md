# Hardware Capability Review — QN19 — 2026-06-18

Scope: product-level review of the newly enabled TMD2772 proximity sensor and
the wider hardware/driver surface that may be useful for the Car Thing product
roadmap. This document is intentionally separate from `carthing_analysis.md`:
that file remains valuable history, but some statements there are now stale.

## Evidence Snapshot

Live device:

```text
host: root@172.16.42.77
device: Car Thing QN19
kernel: Linux 4.9.113 aarch64
date: Thu Jun 18 08:07:00 UTC 2026
```

Live buses and drivers:

```text
I2C 0-002e: tlsc6x_ts        driver=tlsc6x_ts
I2C 2-0018: lis2dh12_accel   driver=none, raw I2C read returns ENXIO
I2C 2-0039: tmd2772          driver=tsl2x7x, IIO=iio:device0
I2C 3-0010: apple_mfi_auth   driver=apple_mfi_auth

IIO iio:device0: tmd2772
IIO iio:device1: meson-g12a-saradc

Input: gpio-keys, rotary@0, aml_vkeypad, tlsc6x_dbg
Devnodes: /dev/dri/card0, /dev/ge2d, /dev/hwrng, /dev/i2c-0/2/3,
          /dev/iio:device0/1, /dev/snd/*, /dev/vhci
```

Raw I2C proof for disputed parts:

```text
LIS2DH12 @ 0x18:
  WHO_AM_I register 0x0f => ENXIO / No such device or address
  interpretation: DT node exists, physical chip does not answer on QN19

MAX20332 @ 0x35:
  register 0x00 => 0x2f
  register 0x03 => 0x12
  register 0x04 => 0x1f
  register 0x07 => 0x0d
  interpretation: physical chip answers; DT node is incomplete because it has
  only reg=<0x35> and no compatible, so Linux does not create a normal device.
```

## TMD2772: What It Really Is

The TMD2772/TMD2772WA family is a combined ambient light sensor, IR proximity
system, and I2C logic module. It is not a camera and not a full directional
gesture sensor. The useful product model is one ALS channel plus one scalar
near/far proximity channel, with IR raw channels available for diagnostics.

Manufacturer capabilities relevant to us:

- Integrated ALS, proximity sensor, and IR LED.
- 1M:1 ALS dynamic range and reduced-gain sunlight support.
- Calibrated/trimmed proximity with programmable LED drive.
- Proximity offset compensation for optical crosstalk.
- Saturation indication to avoid false proximity readings.
- I2C interface at up to 400 kHz.

Live QN19 channels exposed by the current `tsl2x7x` IIO driver:

```text
in_illuminance0_input
in_illuminance0_target_input
in_illuminance0_integration_time
in_intensity0_raw
in_intensity1_raw
in_proximity0_raw
in_proximity0_calibscale
```

Current live sample:

```text
illuminance_input=1
intensity0_raw=54
intensity1_raw=24
proximity_raw=226
```

## Best Product Uses For TMD2772

### 1. Presence-aware screen wake

Use a rolling proximity baseline plus a delta threshold. A hand approaching the
front of the unit should wake/dim the screen through `IdlePowerController`,
not bypass the existing power policy.

Recommended behavior:

- Low-rate sampling while idle, for example 2-5 Hz during dim/off state.
- Faster sampling only for a short gesture window after a rising delta.
- Hysteresis and cooldown, so ambient IR noise does not flicker the display.
- Mode-independent wake is acceptable, but action gestures should be mode-gated.

### 2. Hand wave as a small command surface

The sensor can support a simple "wave/cover/tap-in-air" class of interactions:

- wake screen;
- show route/now-playing overlay;
- dismiss transient notification;
- toggle between dim and active brightness;
- in Play Now only: next/previous should remain conservative because accidental
  gestures near a car dashboard are easy.

Do not promise left/right/up/down gestures. With one proximity channel we only
have time-series shape: baseline, near peak, release, duration, and velocity.

### 3. Ambient-aware brightness

ALS should drive brightness on a perceptual/logarithmic curve with smoothing.
This is a high-value feature because the product is screen-centric and lives in
changing light: desk, car, dark room, sunlight near a window.

Rules:

- use hysteresis and minimum dwell time;
- never change brightness every frame;
- keep manual override possible;
- cap minimum active brightness so the UI remains readable;
- keep "screen off/dim" policy separate from "active brightness".

### 4. Attention/privacy layer

The same sensor can decide whether to show rich content or a quiet display:

- if nobody is near, collapse to clock/route/minimal status;
- if a hand/person approaches, expand metadata, notifications, or controls;
- in Commutator mode, use approach to reveal input/output details only when
  the user is actually interacting.

### 5. Sensor health and calibration

Expose raw ALS/proximity diagnostics in the debug/status page. The first boot
after flashing should learn a baseline and store no irreversible calibration
until we have enough empirical data from different rooms/light levels.

## TMD2772 Implementation Recommendation

Implement `sensor_policy.py` in userspace first.

Minimum viable design:

```text
read tmd2772 IIO channels
  -> rolling baseline for proximity
  -> state machine: far / approach / near / release
  -> IdlePowerController.note_activity("proximity")
  -> optional brightness target update with hysteresis
  -> RuntimeState fields for GUI proof
```

Recommended runtime fields:

```text
sensor.proximity_raw
sensor.proximity_baseline
sensor.proximity_delta
sensor.proximity_zone = far|approach|near|covered
sensor.als_lux
sensor.brightness_auto_target
sensor.last_gesture = none|wake|cover|wave
```

Risk controls:

- feature flag: `CARTHING_SENSOR_POLICY=1`;
- no writes to TMD2772 calibration registers in the first version;
- no irreversible bootfs/DTB change required beyond already enabled
  `enable-proxy=true`;
- GUI must explain "waking", "dimmed", "auto brightness" through status/toast,
  not leave a silent behavior change.

## Hardware Capability Matrix

| Component | Live status | Driver state | Product potential | Recommendation |
|---|---|---|---|---|
| TMD2772 ALS/proximity | Present and working | `tsl2x7x` + IIO | wake/dim by hand, auto brightness, attention-aware UI | Implement userspace policy now |
| TLSC6x touch | Present and working | input event `tlsc6x_dbg` | richer gestures, direct route controls | Refine GUI gestures, no kernel change first |
| Rotary encoder + buttons | Present and working | input events | reliable physical controls | Keep as primary low-latency controls |
| GE2D | Present and working | `/dev/ge2d` | fast UI blit/scale/alpha, dirty rects, overlays | Integrate into GUI rendering path |
| DRM/KMS display | Present and working | `/dev/dri/card0` | stable compositor base | Keep current DRM path; do not revive `meson-fb` blindly |
| T9015 audio / ALSA | Present | `/dev/snd/pcm*` | local playback/capture experiments, USB/audio routes | Research product route; avoid disturbing BT baseline |
| PDM capture | Present as ALSA capture | `/dev/snd/pcm*C*` | voice commands, VAD/STT experiments | Research after resource budget proof |
| MAX20332 USB switch/charger detector | Physically present, raw I2C answers | no Linux device; DT lacks `compatible` | USB charger/accessory detection, OVP state, UART/factory/debrick status, USB switch policy | Build read-only userspace inventory first |
| SARADC | Present | IIO voltage channels | board diagnostics, button/thermal/ID clues | Map channels empirically before product use |
| HWRNG | Present | `/dev/hwrng` | entropy, crypto hygiene | Low-risk service integration/diagnostic |
| Apple MFi auth | Present, cert readable in existing path | module ABI warnings remain | identity/auth research only | Do not make iAP2 promises without fresh proof |
| LIS2DH12 accelerometer | DT node only; raw I2C no answer | no driver | none on QN19 | Mark absent/DNP for this hardware; do not enable |
| IR blaster | DT disabled | no proof of emitter path | remote-control experiments | Defer until pin/emitter proof |
| Ethernet | DT disabled | likely un-routed block | none for current enclosure | Do not enable |
| HDMI / VDIN / video input | DT disabled | no connector/product path | likely SoC leftovers | Do not enable blindly |
| extra SPI/I2C/UART | DT disabled | no peripheral proof | lab expansion only | Keep disabled unless a concrete peripheral is found |
| USB3 PHY | DT disabled | DWC3 host still logs forced host | uncertain; board routing unknown | Do not touch until USB topology is mapped |
| external backlight node | DT disabled | current backlight already works | likely alternate design | Do not enable |

## Reconciliation With Existing Analysis

Stale item:

```text
carthing_analysis.md says runtime proximity_zone already reads the TMD2772.
```

Current interpretation: this is stale. Current runtime diagnostics publish
TMD2772 ALS/proximity values through `resource_policy.py`, but product wake/dim
policy is still pending.

Corrected item:

```text
carthing_analysis.md says LIS2DH12 is DNP / not populated.
```

Current QN19 proof supports this conclusion. The DT node creates a nominal I2C
client, but raw register reads at `0x18` return ENXIO, and no useful IIO/input
surface exists. Treat LIS2DH12 as absent on this hardware unless a different
board revision proves otherwise.

New item:

```text
MAX20332 is not a phantom.
```

The chip answers at `0x35`. The problem is not absence; it is integration. DTB
has no `compatible`, so Linux cannot bind a device. The safest path is a
read-only userspace probe that reports status registers before any control
policy writes are considered.

## What To Enable Or Build Next

### Tier A — implement now

1. `sensor_policy.py` for TMD2772.
2. GUI state/toasts for proximity wake, dim, auto brightness, and sensor debug.
3. GE2D integration for dirty rectangles and overlay composition.
4. MAX20332 read-only inventory in `hardware_inventory.py` / `resource_policy.py`.

### Tier B — research with live proof

1. MAX20332 register interpretation across USB states:
   NCM connected, unplugged, burn/prep mode, charger-only, Mac host.
2. SARADC channel map:
   sample channels while buttons/USB/light/power states change.
3. PDM microphone route:
   prove capture stability and CPU cost before voice features.
4. DRM multiplane/overlay:
   prove it exists on current kernel before designing around it.

### Tier C — explicitly do not enable now

1. LIS2DH12: absent on QN19.
2. Ethernet/HDMI/VDIN/extra buses: likely SoC template leftovers.
3. Linux poweroff/halt path: previously rejected for user-facing shutdown.
4. Any BlueZ-based path: rejected project rule.

## Proposed Product Features For Discussion

1. Hand-presence wake:
   screen wakes when the hand approaches, with no route changes.
2. Retro proximity toast:
   short pixel-style toast: "WAKE", "DIM", "AUTO BRIGHT", "COVERED".
3. Adaptive night mode:
   ALS below threshold switches to calmer contrast/brightness.
4. Attention overlay:
   metadata/details expand only when the user is near.
5. Covered-screen privacy:
   palm/cover gesture collapses notifications or mutes transient overlays.
6. USB intelligence panel:
   MAX20332 reports charger/host/factory/debrick/accessory state.
7. Hardware diagnostics page:
   one screen showing TMD2772, SARADC, MAX20332, GE2D, audio, MFi, HWRNG status.

## Primary Sources

- ams OSRAM TMD27723/TMD2772 product page and datasheet link:
  https://ams-osram.com/products/sensor-solutions/ambient-light-color-spectral-proximity-sensors/ams-tmd27723-ambient-light-sensor
- STMicroelectronics LIS2DH12 product page:
  https://www.st.com/en/mems-and-sensors/lis2dh12.html
- STMicroelectronics LIS2DH12 datasheet:
  https://www.st.com/resource/en/datasheet/lis2dh12.pdf
- Analog Devices MAX20332 product page:
  https://www.analog.com/en/products/max20332.html
- Analog Devices MAX20332 datasheet:
  https://www.analog.com/media/en/technical-documentation/data-sheets/MAX20332.pdf
- Linux `CONFIG_VIDEO_MESON_GE2D` summary:
  https://www.kernelconfig.io/CONFIG_VIDEO_MESON_GE2D
- TI TIDA-00754 reference design for ALS/proximity-driven backlight:
  https://www.ti.com/tool/TIDA-00754
