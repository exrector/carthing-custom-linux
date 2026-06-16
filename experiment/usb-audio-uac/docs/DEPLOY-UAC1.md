# Car Thing — UAC1 USB Audio Deployment

Date: 2026-05-24  
Device: SN Q917 (8559RP88Q917), IP 172.16.42.77

---

## What changed vs. accel build

| defconfig option | before | after |
|-----------------|--------|-------|
| `CONFIG_USB_G_NCM` | `=y` | `is not set` |
| `CONFIG_USB_CONFIGFS_F_UAC1` | `is not set` | `=y` |

**Why remove g_ncm:** the legacy `g_ncm` built-in gadget claims the UDC (`ff400000.dwc2_a`)
immediately at boot, before configfs is mounted. This prevents composite gadget setup.
With `g_ncm` removed, the UDC is free until the S04-usbgadget init script binds a
configfs composite (NCM + UAC1).

---

## New kernel Image

Path (after build):
`artifacts/kernel-build-gcc6-nixos-20260524/nixos-superbird/out-uac1/kernel/Image`

---

## Deploy procedure

### Step 1 — Flash new kernel (bootfs-only)

The kernel Image replaces the one inside `boot_part_accel.bin`. DTB, initrd and
bootargs are unchanged.

```sh
# On macOS — create new bootfs with UAC1 kernel
cd ~/Documents/ПРОЕКТЫ/carthing-device-backups/artifacts/kernel-build-gcc6-nixos-20260524

# Build boot_part.bin from:
#   Image  = out-uac1/kernel/Image
#   initrd = boot-ready-tdm-unmute/initrd       (unchanged)
#   DTB    = boot-ready-tdm-unmute/superbird.dtb  (unchanged)
#   bootargs = boot-ready-tdm-unmute/bootargs.txt (unchanged)
```

Use the same `flash-bootfs-only.py` script from previous builds.

### Step 2 — Add S04-usbgadget to rootfs

The rootfs at `/dev/root` is currently mounted read-only (ext4). Remount it RW to
add the configfs setup script.

```sh
# On Car Thing (via SSH)
mount -o remount,rw /
cp /tmp/S04-usbgadget /etc/init.d/S04-usbgadget
chmod +x /etc/init.d/S04-usbgadget
mount -o remount,ro /
```

Upload the script:
```sh
# On macOS
cat /tmp/S04-usbgadget | ssh root@172.16.42.77 \
  "mount -o remount,rw / && cat > /etc/init.d/S04-usbgadget && chmod +x /etc/init.d/S04-usbgadget && mount -o remount,ro /"
```

### Step 3 — Reboot and verify

After reboot, verify composite gadget is active:
```sh
# On Car Thing
cat /sys/kernel/config/usb_gadget/g1/UDC
# → ff400000.dwc2_a
ls /sys/kernel/config/usb_gadget/g1/functions/
# → ncm.usb0   uac1.usb0
```

Verify NCM still works (SSH at 172.16.42.77 must still work):
```sh
# On macOS
ssh root@172.16.42.77 "echo SSH OK"
```

---

## macOS USB audio test

After reboot with composite gadget:

1. Disconnect and reconnect USB-C cable to macOS.
2. On macOS: **System Settings → Sound → Output** — should show "Car Thing".
3. Select "Car Thing" as output device.
4. Play audio from macOS (Music, Safari, etc.) → should go to Car Thing.

On Car Thing, the UAC1 playback endpoint appears as a new ALSA device (different
from `pcmC0D0p`). To route USB audio → T9015 DAC, run:

```sh
ssh root@172.16.42.77 "python3 /run/ct_alsa_play.py" < /dev/null &
# or use a loopback: arecord from uac1 → aplay to pcmC0D0p
```

For a quick loopback test using Python only (no aplay):

```python
# /run/ct_usb_loopback.py
# Reads from UAC1 capture (USB input from macOS) → writes to pcmC0D0p (T9015 DAC)
```

---

## Rollback

If boot loops: flash stock bootfs from:
`artifacts/flash-restore-stock-bootfs-20260524/bootfs.bin`

The accel build bootfs (known-good with T9015 playback):
Recreate from `boot-ready-tdm-unmute/` — that build had `g_ncm` so USB network
still works there.

---

## UAC1 gadget parameters (configured in S04-usbgadget)

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `p_chmask` | 3 | stereo playback (2ch) |
| `p_srate`  | 48000 | 48 kHz |
| `p_ssize`  | 2 | S16_LE (2 bytes/sample) |
| `c_chmask` | 0 | no USB capture endpoint |

---

## Audio routing inside Car Thing

```
macOS audio output
    │ USB-C → UAC1 gadget
    ▼
/dev/snd/pcmC1D0c  (or similar — UAC1 capture endpoint on Car Thing side)
    │ loopback script
    ▼
/dev/snd/pcmC0D0p  (T9015 DAC playback)
    │ analog
    ▼
T9015 line-out → (wiring TBD: USB-C alt mode / PCB pads / internal speaker driver)
```

The UAC1 function in the kernel presents:
- A **capture** endpoint to Car Thing (`/dev/snd/pcmC1D0c` or similar) — this is where
  Car Thing READS the audio that macOS sends.
- A **playback** endpoint visible to macOS — macOS writes audio here.

The loopback Python script reads from the UAC1 capture endpoint and writes to T9015
playback, connecting the USB audio stream to the DAC.
