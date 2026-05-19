# Car Thing — Hardware Inventory

Snapshot from device №1 running firmware `device1-v1-working-20260518`,
collected by `tools/hw_inventory.sh` on 2026-05-19. Read-only — no
writes to any /sys node.

## Audio — capture only

`/proc/asound/cards`:
```
 0 [AMLAUGESOUND   ]: AML-AUGESOUND - AML-AUGESOUND
```

`/proc/asound/devices`:
```
  0: [ 0]   : control
 24: [ 0- 0]: digital audio capture
 33:        : timer
```

`/dev/snd/`:
```
controlC0          mixer control
pcmC0D0c           capture device (no playback exposed)
timer
```

PCM info from `/proc/asound/card0/pcm0c`:
```
card: 0
device: 0
subdevice: 0
stream: CAPTURE
id: PDM-dummy-alsaPORT-pdm dummy-0
subdevices_count: 1
```

**Observations:**
- Stream is **CAPTURE only**. No `pcmC0D0p` (playback) node exposed by
  this firmware build.
- The driver id contains `PDM` — captured signal is Pulse-Density-Modulation
  from a digital microphone path.
- Number of channels, supported sample rates, and microphone count are
  not exposed by `/proc` and require querying `SNDRV_PCM_IOCTL_HW_PARAMS`
  or installing `alsa-utils` (not currently on rootfs).

## Display backlight

```
/sys/class/backlight/aml-bl
  actual_brightness: 100
  brightness:        100
  max_brightness:    255
  type:              raw
```

Single PWM channel, writable. Underlying device: `platform/backlight/backlight/aml-bl`.

## Ambient Light + Proximity — TMD2772

I2C: bus 2, address 0x39. Linux IIO node: `/sys/bus/iio/devices/iio:device0`.
Device-tree compatible: `amstaos,tmd2772`.

```
name: tmd2772
in_intensity0_raw:        ~85    (clear / visible channel)
in_intensity1_raw:        ~39    (IR channel)
in_proximity0_raw:        0
in_illuminance0_input:    1      (lux, derived from lux table)
in_illuminance0_integration_time: 0.111   (111 ms)
```

Full attribute set:
```
in_illuminance0_calibrate
in_illuminance0_calibscale_available
in_illuminance0_input
in_illuminance0_integration_time
in_illuminance0_integration_time_available
in_illuminance0_lux_table
in_illuminance0_target_input
in_intensity0_calibbias
in_intensity0_calibscale
in_intensity0_raw
in_intensity1_raw
in_proximity0_calibrate
in_proximity0_calibscale
in_proximity0_calibscale_available
in_proximity0_raw
events/        (threshold-driven interrupts)
```

Working in this firmware. Both ambient light (lux) and proximity available
without setup.

## Accelerometer — LIS2DH12 (present, NOT bound)

I2C: bus 2, address 0x18. Device-tree compatible: `st,lis2dh12-accel`.

```
/sys/bus/i2c/devices/2-0018/
  modalias: i2c:lis2dh12-accel
  driver:   (missing)
```

The chip is wired on the board and described in the device tree, but
**no kernel driver claims it** in this firmware. As a result there is
no IIO/input node, no axis readings, no tap/wake events.

## MFi authentication chip — Apple AuthCo (present, NOT bound)

I2C: bus 3, address 0x10. Device-tree compatible: `apple_mfi_auth`.

```
/sys/bus/i2c/devices/3-0010/
  modalias: i2c:apple_mfi_auth
  driver:   (missing)
```

Same situation as the accelerometer — silicon present, no driver bound.
The clean-room iAP2 work talks to it via raw `/dev/i2c-3`.

## Touchscreen — TLSC6x

Documented separately in [input-map.md](input-map.md). I2C bus 0, address 0x2e,
driver bound, `event3`.

## Thermal zones

```
thermal_zone0  soc_thermal        31.3 °C
thermal_zone1  ddr_thermal        31.5 °C
thermal_zone2  bluetooth_thermal  24.0 °C
thermal_zone3  dram_thermal       29.9 °C
thermal_zone4  pcb_thermal        30.0 °C
```

Two cooling devices declared (`cooling_device0`, `cooling_device1`),
not investigated.

## SAR ADC — `meson-g12a-saradc`

8-channel ADC on the Amlogic SoC, exposed as `iio:device1`:

```
in_voltage0..in_voltage7  raw and mean
in_voltage_scale: 439.453125  (mV per raw unit, scaled)
```

Channel-to-signal mapping is **not** in this probe; resolving requires
reading the device tree (`/sys/firmware/devicetree/base/...`). Typical
candidates on Amlogic platforms: NTC thermistor, battery monitor pin,
boot mode strap.

## LEDs

`/sys/class/leds` does not exist on this firmware — no LED class device
is registered. Whether any indicator LED is physically on the board
cannot be determined from this probe alone.

## Network interfaces

```
eth0      — (kernel-side)
lo
usb0      — NCM gadget exposed over USB to the host
```

## I2C client summary

| Bus-addr | Device           | Driver bound | Purpose                |
|----------|------------------|--------------|------------------------|
| 0-002e   | tlsc6x_ts        | yes          | touchscreen            |
| 2-0018   | lis2dh12-accel   | **no**       | accelerometer (idle)   |
| 2-0039   | tmd2772          | yes          | light + proximity      |
| 3-0010   | apple_mfi_auth   | **no**       | Apple MFi crypto chip  |

## Source log

Raw probe output: `docs/captures/hw-2026-05-19.log` (418 lines).
