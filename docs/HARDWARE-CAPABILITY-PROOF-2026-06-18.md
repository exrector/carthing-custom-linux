# Hardware Capability Proof — QN19 — 2026-06-18

Scope: first DTB capability pass after the owner noticed that useful hardware
features can remain present but disabled by DTB properties after earlier
rollback/cleanup cycles.

## TMD2772 Proximity

Problem:

```text
/proc/device-tree/soc/cbus@ffd00000/i2c@1d000/tmd27721@39/enable-proxy = false
/proc/device-tree/soc/cbus@ffd00000/i2c@1d000/tmd27721@39/enable-als = true
dmesg: tsl2x7x 2-0039: Proxy Sensor is disabled.
dmesg: tsl2x7x 2-0039: Ambient Light Sensor is enabled.
```

Before the DTB change, `in_proximity0_raw` stayed at `0` during a 25 second
sample window. ALS/IR channels were alive, but the proximity engine was not.

Change:

```text
superbird.dtb:
  /soc/cbus@ffd00000/i2c@1d000/tmd27721@39
  enable-proxy = "true"
  enable-als   = "true"
```

The live p1 DTB was backed up before replacement:

```text
/run/carthing-state/superbird.dtb.before-proxy-20260618-1100
sha256 a95d7cbaabddb1a7c7ee2ad51fa459c28cceb2ade67896f01eb4881d16593237
```

After reboot:

```text
/run/carthing-state/superbird.dtb
sha256 782db0c7792b51372d1b75d820374b0a0cf203b2c614ade634741c7c55581b59

/proc/device-tree/.../tmd27721@39/enable-proxy = true
/proc/device-tree/.../tmd27721@39/enable-als = true
dmesg: tsl2x7x 2-0039: Proxy Sensor is enabled.
dmesg: tsl2x7x 2-0039: Ambient Light Sensor is enabled.
```

Runtime sensor proof:

```text
resource_policy.sensors.tmd2772.proximity_raw = 217
direct sysfs in_proximity0_raw = 202
30 second sample after reboot: proximity_raw roughly 120..230
```

Interpretation:

- TMD2772 proximity is now genuinely enabled at the driver level.
- The default IIO proximity event thresholds are still not product-ready:
  `rising_value=512`, `falling_value=0`, while the live baseline was around
  `120..230`. The future wake/dim feature should use calibrated baseline/delta
  or lower explicit thresholds, not blindly rely on the current event defaults.
- Backlight control already exists in `IdlePowerController`; the missing next
  layer is a small sensor policy loop that maps proximity/ALS into
  `note_activity()` / brightness changes.

## Bootfs Baseline

The canonical bootfs images were updated with the same DTB and FAT clean byte
preserved:

```text
image/bootfs.bin sha256:              f01e3078a7aca5534c0317459fd20073049091db393646493117deccf6a18ada
source/base-bundle/bootfs.bin sha256: f01e3078a7aca5534c0317459fd20073049091db393646493117deccf6a18ada
FAT boot-sector byte 0x25: 0x00
embedded superbird.dtb enable-proxy: true
```

The previous clean GE2D bootfs was:

```text
6e99a75c57e38acab5be5b818f559132a4b7a167e7ccfa80e4e3ce1aedd7df3e
```

## Disabled / False Candidate Pass

These candidates were observed in the current DTB or boot logs. They are not
equally safe to enable.

| Candidate | Current state | Decision |
|---|---|---|
| TMD2772 proximity | `enable-proxy=false` | Enabled now. Low-risk: same driver already owned ALS. |
| LIS2DH12 accelerometer | I2C client `2-0018 lis2dh12_accel`, no IIO/input surface | Research next. Needs binding/interface proof, not a blind DTB status flip. |
| MAX20332 USB-C mux | DTB node has only `reg=<0x35>`; boot log has `modalias failure` | Research next. Needs a real `compatible` contract or userspace raw-I2C tool. |
| IR blaster | `status="disabled"` | Defer. Useful, but needs pin/protocol proof and no immediate product dependency. |
| Ethernet / HDMI / VDIN / extra UART/SPI/I2C / external backlight | `status="disabled"` | Do not enable blindly. Likely alternate SoC blocks, absent board routing, or unused outputs. |

## Next Product Step

Implement a sensor policy in userspace:

1. Sample TMD2772 proximity and ALS/IR at a low rate.
2. Maintain a rolling baseline for proximity.
3. Treat a strong positive delta as hand-present/hand-wave.
4. Call `IdlePowerController.note_activity("proximity")` to wake the screen.
5. Optionally apply conservative ALS-based active brightness with hysteresis.

This should be deployed as a reversible runtime feature after the DTB-level
proof above, not mixed into the DTB change itself.
