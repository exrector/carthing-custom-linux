# Full Hardware / Driver Audit — QN19 — 2026-06-18

Scope: full live audit of the QN19 Car Thing hardware/driver surface as Linux
sees it today, reconciled with the current project analysis. The point is to
decide which product functions are worth implementing, not to blindly enable
every SoC block that appears in Device Tree.

This document supersedes scattered hardware notes as the current review surface.
It does not delete older analysis because older documents are useful history,
but their claims must be treated as stale unless confirmed here or by newer
live proof.

## Evidence Collected

Live capture:

```text
device: QN19
host: root@172.16.42.77
kernel: Linux 4.9.113 aarch64
capture: 2026-06-18 08:16 UTC
```

Inputs used:

```text
/proc/device-tree summary
/sys/bus/*
/sys/class/*
/dev
/proc/devices
/proc/modules
/proc/config.gz
/proc/asound/cards
/proc/asound/pcm
dmesg
raw I2C reads for disputed 0x18 and 0x35 devices
```

Important audit rule:

```text
DTB node != physical proof
char major != product-ready feature
kernel config != board routing
```

## Executive Conclusions

1. The board has more useful live hardware than our current runtime inventory
   exposes. `hardware_inventory.py` is too narrow.
2. The most immediate missed product layer is still TMD2772: proximity is now
   enabled and working, but there is no product policy loop yet.
3. MAX20332 is physically present and answers over I2C. It is not currently a
   Linux device because its DTB node has no `compatible`. This is the next
   important hardware-inventory gap.
4. LIS2DH12 should be treated as absent on QN19. Device Tree creates a nominal
   client, but raw reads at `0x18` return ENXIO.
5. `/dev/vad`, PDM capture, Amlogic audio/video/media nodes, and GE2D are real
   driver surfaces. They are useful, but must be classified as research until
   small proof programs show stable API and CPU/power cost.
6. Ethernet, HDMI, VDIN, extra UART/SPI/I2C, IR blaster, USB3 PHY, external
   backlight, Wi-Fi, and Mali GPU should not be enabled just because they exist
   in the SoC or kernel tree. They lack board/product proof.

## Current Runtime Inventory Coverage

`overlay/usr/lib/carthing/hardware_inventory.py` currently detects:

```text
display_drm
backlight
touch
encoder
buttons
accel_lis2dh12 as driver-bound only
als_prox_tmd2772
audio_playback_t9015
audio_capture_pdm
thermal_zones count
zram
hwrng
usb_host
efuse_usid
mfi_auth / mfi_chip
```

This is a good start, but incomplete. It should be extended with:

```text
max20332_raw_i2c
saradc channel snapshot
vad_devnode
ge2d_devnode and self-test status
drm connector/plane summary
usb_gadget active functions
usb_host bus/physical-port status
watchdog
rtc
unifykeys / efuse readable keys
crypto_dma availability
audio raw nodes: audiodsp0, amaudio, media.audio
video raw nodes: amvideo, vfm, videosync, media.decoder/parser/video
```

## Product-Ready / Directly Usable Surfaces

| Hardware / block | Live proof | Driver / interface | What it is used for generally | Product use for us | Decision |
|---|---|---|---|---|---|
| LCD panel ST7701S 480x800 | dmesg reports `ST7701S, mipi, 480x800`; DRM connector `LVDS-1 connected` | Amlogic LCD + DRM/KMS, `/dev/dri/card0` | embedded HMI display | main GUI | Keep as canonical display path |
| Backlight PWM | `/sys/class/backlight/aml-bl`, max 255 | `amlogic, backlight-g12a`, PWM_F | display brightness / dimming | auto-brightness, idle dim, night mode | Use now through existing power policy |
| DRM/KMS | `/dev/dri/card0`, mode `panel` | `CONFIG_DRM_MESON=y`, `drm-lcd`, `drm-vpu` | modern direct display composition | GUI compositor, overlays | Keep; do not revive framebuffer path |
| Touchscreen TLSC6x | I2C `0-002e`, input `event3`, dmesg probe OK | `tlsc6x_ts` | direct touch UI | richer gestures, route selection, debug panel | Use now; improve gesture layer |
| Rotary encoder | input `event1` | `rotary-encoder` | physical precise control | primary low-risk control | Keep as primary control |
| Buttons / GPIO keys | input `event0`, `aml_vkeypad` event2 | `gpio-keys-polled`, keypad | physical actions / recovery | mode/back/prep actions | Keep |
| TMD2772 ALS/proximity | I2C `2-0039`, IIO `iio:device0`, prox/ALS channels live | `tsl2x7x` | auto brightness, proximity wake, cover detection | wake/dim by hand, attention UI, night mode | Implement userspace sensor policy |
| GE2D | `/dev/ge2d`, dmesg 499 MHz, IRQ 40 | `amlogic, ge2d-g12a`, `CONFIG_AMLOGIC_MEDIA_GE2D=y` | 2D blit/scale/fill/blend | faster dirty rect GUI, overlays | Integrate with GUI after small tests |
| Bluetooth controller | dmesg BCM20703A2, HCI UART ttyS1 at 3 Mbit | Broadcom HCI UART, `CONFIG_BT_HCIUART_BCM=y`, `/dev/vhci` | BLE/Classic audio/control | current iPhone + speaker route model | Keep current non-BlueZ stack |
| USB NCM gadget | `usb0` carrier up; ConfigFS functions compiled | DWC2 device, `g_ncm`, `USB_CONFIGFS_*` | device networking to host | SSH/recovery/control plane | Keep as baseline lifeline |
| eMMC | `mmcblk0` 3.69 GiB, p1/p2 | Amlogic MMC | boot/rootfs/storage | P1 boot/state + P2 rootfs | Keep P1/P2 architecture |
| T9015 audio playback | ALSA card `AML-AUGESOUND`, pcm `00-00 playback` | `aml_codec_T9015`, TDM-A | local DAC/I2S audio | local sink, diagnostics, possible USB/audio paths | Research product route without breaking BT |
| PDM capture | ALSA pcm `00-01 capture` | `g12a-snd-pdm` | microphone array capture | voice experiments, diagnostics | Research with CPU/power proof |
| Thermal zones | soc/ddr/bluetooth/dram/pcb temps visible | Amlogic thermal + generic zones | thermal protection/telemetry | health page, throttling hints | Expose in runtime/GUI |
| HWRNG | `/dev/hwrng` | `amlogic,meson-rng` | entropy source | crypto hygiene, diagnostics | Add low-risk service/metric |
| efuse / unifykeys | `/dev/efuse`, `/dev/unifykeys`, dmesg keys: mac/mac_bt/mac_wifi/usid/f_serial | Amlogic efuse/unifykey | factory identity / calibration keys | stable identity/provenance | Read only, never mutate |
| zram | `/dev/zram0`, kernel `CONFIG_ZRAM=y` | zram block | compressed swap/memory cushion | runtime resilience under Python/UI | Keep and report status |
| watchdog / RTC | `/dev/watchdog0`, `/dev/rtc0` | Meson WDT, virtual RTC | hang recovery/time source | lab watchdog only after policy | Do not arm user-facing watchdog yet |

## Present But Raw / Research Surfaces

These are real surfaces, but not yet product-safe APIs.

| Hardware / block | Live proof | Driver / interface | General use | Why it matters | Next proof |
|---|---|---|---|---|---|
| MAX20332 USB charger/switch detector | raw I2C `0x35` answers; `DEVICE ID=0x2f`; DTB has node but no `compatible` | no bound Linux device; raw `/dev/i2c-2` only | USB charger/accessory detection, OVP, USB/UART switch, factory/debrick status | USB intelligence panel, safer USB mode decisions | read-only register decoder in `hardware_inventory.py` |
| Amlogic VAD | `/dev/vad`, char major 271 | proprietary Amlogic VAD DSP node | low-power voice activity wake | possible voice wake without CPU loop | ioctl/API discovery with no always-on STT |
| audiodsp / amaudio | `/dev/audiodsp0`, `/dev/amaudio*` | Amlogic audio DSP/legacy audio nodes | decode/mix/DSP pipeline | possible offload or legacy codec path | enumerate ioctls; do not route product audio yet |
| Amlogic video decode stack | `/dev/amvideo`, `/dev/vfm`, `/dev/videosync`, `media.decoder/parser/video`, `vcodec_dec`, `vdec` | Amlogic media/vcodec nodes | hardware video decode/display pipeline | future visualizer/video/artwork experiments | minimal decode proof, memory/power cost |
| HEVC encoder | DTB `hevc_enc` okay | `cnm, HevcEnc` | hardware video encode | probably low product value | Defer |
| DRM OSD2 / planes | kernel has `CONFIG_AMLOGIC_MEDIA_FB_OSD2_ENABLE=y`; DRM live has one connector | DRM/KMS + Amlogic OSD | overlay planes / cursor / composition | notification overlays without full redraw | run DRM plane enumeration/proof |
| SARADC | IIO `meson-g12a-saradc`, voltage0..7 live | `amlogic,meson-g12a-saradc` | analog board sensing | detect board IDs, buttons, rails, diagnostics | empirical channel map under state changes |
| USB host / xHCI | xHCI buses exist, `dwc3 forced to host`, `usb2 unsupported hub`; USB3 PHY disabled | DWC3 host + USB2 PHY | attach USB peripherals | possible lab USB accessories | map physical port behavior; do not depend on it |
| USB composite functions | kernel has NCM/ECM/RNDIS/UAC1/UAC2/MIDI/HID/MassStorage/MTP/PTP/ACC; NCM/UAC2/storage have prior live tests | ConfigFS gadget | present device to Mac/PC as composite gadget | USB reserve mode, audio/HID/MIDI experiments | productize tested NCM/UAC2/storage; prove remaining profiles on macOS without losing NCM |
| MFi auth chip | I2C `3-0010`, `/dev/apple_mfi`, cert len 608; module ABI warnings | proprietary module + I2C | Apple accessory authentication | identity/auth research | treat as research; no iAP2 promise without proof |
| Amlogic crypto DMA | dmesg AES/SHA DMA; DTB `aml_aes`, `aml_sha`, `aml_tdes` okay | kernel crypto drivers | hardware crypto acceleration | hashes/signing/diagnostics | verify `/proc/crypto` actual driver selection |
| DDR bandwidth / DMC monitor | DTB okay, `/dev/memory_bandwidth` | Amlogic monitor | memory bandwidth telemetry | performance profiling | expose read-only metric if stable |
| uinput / uhid | `/dev/uinput`, `/dev/uhid` | Linux virtual input/HID | synthetic input devices | USB/Bluetooth control experiments | use only for explicit gadget/HID modes |
| GPIO / PWM | gpiochips, PWM nodes | Amlogic GPIO/PWM | board control, LEDs, backlight | diagnostics, possible hardware toggles | only after pin map proof |

## Absent, Incomplete, Or Do-Not-Enable Surfaces

| Candidate | Current state | Why not now | Decision |
|---|---|---|---|
| LIS2DH12 accelerometer | DTB node and I2C client name exist; raw `0x18` reads return ENXIO; no driver bound | not physically answering on QN19 | Treat as DNP/absent |
| MAX20332 kernel driver binding | chip present, but DT node lacks `compatible`; boot log has modalias failure | binding/control writes could disturb USB/power path | Userspace read-only first |
| Ethernet MAC | DTB disabled | no connector/PHY proof; current product uses USB NCM | Do not enable |
| HDMI / HDMITX | DTB disabled; kernel `CONFIG_AMLOGIC_HDMITX` not set | no HDMI connector/product route | Do not enable |
| VDIN / video input | DTB disabled; kernel `CONFIG_AMLOGIC_MEDIA_VIN` not set | no camera/input connector proof | Do not enable |
| IR blaster | DTB disabled; kernel `CONFIG_AMLOGIC_IRBLASTER_CORE` not set | no emitter/pin proof | Defer / likely no |
| extra UARTs | some serial nodes disabled; ttyS0 console and ttyS1 BT are used | enabling random UARTs risks pin conflicts | Do not enable without pin map |
| extra SPI/I2C buses | disabled DTB nodes | no attached peripheral proof | Do not enable |
| USB3 PHY | DTB disabled; DWC3 host still appears | board routing unclear; host path already odd | Do not touch yet |
| `meson-fb` | DTB disabled; DRM works | old framebuffer path would compete with DRM | Keep disabled |
| external backlight | `bl_extern` disabled; current PWM backlight works | alternate panel design | Keep disabled |
| Wi-Fi | combo chip family may include Wi-Fi, but kernel has `CONFIG_WLAN` off and no wlan device | no product need; driver absent | Do not pursue now |
| Mali GPU | no `/dev/mali`/render node; not in current product path | no userspace driver/proof | Do not depend on GPU |
| Linux poweroff/halt | known bad product behavior in previous testing | can put device into bad USB/burn-mode-like states | Keep rejected for user-facing UI |

## Stale Or Dangerous Claims To Correct Mentally

| Older claim | Current audit correction |
|---|---|
| `proximity_zone` already reads TMD2772 | Stale. TMD2772 values are exposed in diagnostics, but product wake/dim policy is not implemented yet. |
| LIS2DH12 might be useful if driver is enabled | Not on QN19. It does not answer over raw I2C. |
| MAX20332 is only a phantom DT node | Wrong. It physically answers at `0x35`; only Linux integration is missing. |
| USB profiles are all product-ready because ConfigFS functions exist | Too strong. NCM, UAC2 audio, and mass-storage have live tests; remaining profiles still need proof and all product profiles must preserve NCM recovery. |
| VAD means voice wake is ready | Too strong. `/dev/vad` exists, but the ioctl/API contract is not proven. |
| Video hardware means video feature is ready | Too strong. Amlogic media nodes exist; product decode/display route is unproven. |

## Recommended Feature Candidates For Discussion

### Highest value / lowest risk

1. **TMD2772 sensor policy**
   - wake/dim screen by hand presence;
   - auto brightness with hysteresis;
   - near/covered/approach state in GUI;
   - no DTB change needed now.

2. **Hardware diagnostics screen**
   - TMD2772 raw/zone;
   - MAX20332 USB status;
   - thermal zones;
   - zram/memory;
   - GE2D presence/self-test;
   - audio card/capture;
   - current USB gadget mode.

3. **MAX20332 read-only USB intelligence**
   - decode DEVICE ID, STATUS 1, STATUS 2, CONTROL registers;
   - show charger/host/unknown/accessory/factory/debrick indicators;
   - no writes in first version.

4. **GE2D GUI acceleration**
   - dirty rect copy/fill/scale;
   - notification/toast overlays;
   - reduce CPU spikes during Bluetooth/audio work.

### Medium risk / good innovation potential

5. **VAD/PDM voice proof**
   - first prove low-power VAD event behavior;
   - then evaluate offline command recognition;
   - never restore a heavy always-on voice loop.

6. **SARADC board-state map**
   - sample channels while USB/power/buttons/display states change;
   - use only after channel identity is known.

7. **USB reserve profiles**
   - `ncm+audio` and mass-storage already have prior proof;
   - `ncm+hid`, `ncm+midi`, RNDIS/ECM remain candidates;
   - each product profile must keep a recovery path.

8. **DRM plane / OSD2 proof**
   - enumerate planes;
   - prove independent overlay updates;
   - use for toasts/call/route banners if stable.

### Research only

9. **Amlogic video decode / media nodes**
   - possible visualizer/video/artwork experiments;
   - not core product until proof shows low CPU/memory cost.

10. **MFi/iAP2 extension**
   - only after exact supported services are proven;
   - do not assume library/artwork access.

## Runtime Inventory Improvements Needed

The practical fix for not missing hardware again is to make `hardware_inventory`
closer to this audit. Recommended fields:

```text
max20332.present
max20332.device_id
max20332.status1
max20332.status2
max20332.control1

sensor.tmd2772.present
sensor.tmd2772.als
sensor.tmd2772.proximity
sensor.tmd2772.proximity_baseline

saradc.channels[0..7].raw/input
thermal.zones[]
ge2d.present
ge2d.selftest
drm.connector
drm.mode
drm.planes_count
usb.gadget.active_profile
usb.host.buses
audio.alsa.cards
audio.pdm_capture
audio.vad_devnode
video.amlogic_nodes_present
crypto.aml_sha_dma
crypto.aml_aes_dma
watchdog.present
```

This should feed the GUI/debug screen and release diagnostics. The GUI must not
infer capabilities from old documentation.

## Decision List

| Decision | Rationale |
|---|---|
| Implement TMD2772 policy next | Already live, low risk, visible product value |
| Add MAX20332 read-only probe next | Real chip, currently invisible to runtime, useful USB/power context |
| Expand hardware diagnostics GUI | Prevents future hidden disabled/false states |
| Keep LIS2DH12 out | Absent on QN19 |
| Keep HDMI/Ethernet/VDIN/extra buses disabled | No board/product proof |
| Keep DRM as display source of truth | It is live and current GUI already depends on it |
| Treat Amlogic media/VAD/audio DSP as research | Nodes exist, API/product contract not proven |

## Appendix: Key Live Facts

```text
I2C 0-002e: tlsc6x_ts        driver=tlsc6x_ts
I2C 2-0018: lis2dh12_accel   driver=none, raw I2C ENXIO
I2C 2-0039: tmd2772          driver=tsl2x7x, IIO=iio:device0
I2C 3-0010: apple_mfi_auth   driver=apple_mfi_auth

TMD2772 sample:
  illuminance_input=0
  intensity0_raw=15
  intensity1_raw=8
  proximity_raw=1340

SARADC channels:
  voltage0..7 present through iio:device1

ALSA:
  00-00 TDM-A-T9015 playback/capture
  00-01 PDM capture

Display:
  DRM connector card0-LVDS-1 connected/enabled
  mode panel, 480x800
  backlight aml-bl brightness 155/255

Thermal:
  soc, ddr, bluetooth, dram, pcb zones present

Devnodes:
  /dev/ge2d
  /dev/vad
  /dev/audiodsp0
  /dev/amaudio*
  /dev/amvideo
  /dev/media.*
  /dev/iio:device0/1
  /dev/i2c-0/2/3
  /dev/hwrng
  /dev/efuse
  /dev/unifykeys
  /dev/apple_mfi
  /dev/watchdog0
  /dev/zram0
```
