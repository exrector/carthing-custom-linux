# MFi Low-Level Probe

Purpose:

- keep the MFi revival work at the lowest possible layer
- avoid pulling any inherited Spotify userspace back into the active system
- give the project one simple executable that can validate `/dev/apple_mfi`
  and the reverse-engineered ioctl contract

Tool:

- `carthing-mfi-probe`
- direct fallback commands:
  - `carthing-mfi-probe raw-info`
  - `carthing-mfi-probe raw-sign <challenge_hex>`

Commands:

- `carthing-mfi-probe info`
- `carthing-mfi-probe certlen`
- `carthing-mfi-probe serial`
- `carthing-mfi-probe response > pkcs7.bin`
- `carthing-mfi-probe sign <challenge_hex>`

What it depends on:

- only `/dev/apple_mfi`
- no BlueZ
- no `bluetoothd`
- no D-Bus
- no old Spotify runtime pieces

Current live state on the 2026-05-18 working image:

- `/dev/apple_mfi` is absent
- no `apple_mfi` modules are visible from the custom rootfs
- `dtb` still contains `spotify_mfi_i2c_pins`
- `/sys/bus/i2c/devices/3-0010` exists on the live device
- `/sys/bus/i2c/devices/3-0010/of_node/compatible = apple_mfi_auth`
- `/sys/bus/i2c/devices/3-0010/modalias = i2c:apple_mfi_auth`
- `/sys/bus/i2c/devices/3-0010/driver` is missing
- `/proc/modules` has no `apple_mfi*`
- `/proc/devices` has no `apple_mfi_ioctl`
- `/lib/modules/$(uname -r)` has no `apple_mfi*` files or aliases
- `/dev/i2c-3` can talk to `0x10` directly
- naive raw reads return only zero-state values until the chip is nudged through
  its command-style prepare/wake flow

Meaning:

- device-tree presence is not the blocker anymore
- the blocker is missing driver binding / missing module path for `apple_mfi_auth`
- direct userspace I2C is possible, so a clean-room rewrite does not need to
  rediscover the bus wiring
- the next missing piece is the driver-side prepare/wake behavior before
  challenge/signature operations become meaningful
- the cert path is no longer hypothetical: it already works through raw I2C
- the right next step is no longer "bring back old userspace", and not even
  strictly "bring back `/dev/apple_mfi` first"; it is to clean-room the chip's
  command semantics on top of `/dev/i2c-3`
- once the sign path is understood, a new helper can choose either backend:
  `/dev/apple_mfi` if it exists, or direct `/dev/i2c-3` if it does not

Minimal live proof command used on the working image:

```sh
ssh root@172.16.42.77 '
  [ -e /dev/apple_mfi ] && echo APPLE_MFI_DEV=yes || echo APPLE_MFI_DEV=no
  [ -e /sys/bus/i2c/devices/3-0010 ] && echo I2C_3_0010=yes || echo I2C_3_0010=no
  readlink /sys/bus/i2c/devices/3-0010/driver 2>/dev/null || echo DRIVER_LINK=none
  cat /sys/bus/i2c/devices/3-0010/modalias
  grep apple_mfi /proc/modules /proc/devices 2>/dev/null || true
'
```

Minimal raw-I2C proof collected on the working image:

```sh
ssh root@172.16.42.77 '
  i2cdetect -y 3
  i2ctransfer -f -y 3 w1@0x10 0x21 r1
  i2ctransfer -f -y 3 w1@0x10 0x12 r8
'
```

Observed state:

- address `0x10` is present on bus `3`
- direct `0x21` read returns `0x00`
- direct `0x12` read returns all zero bytes
- direct `0x30` certlen path is not yet usable without the original
  prepare/wake logic

Raw-I2C breakthrough collected later on the same working image:

```sh
ssh root@172.16.42.77 '
  i2cset -f -y 3 0x10 0x00
  i2ctransfer -f -y 3 r4@0x10
  i2cset -f -y 3 0x10 0x01
  i2ctransfer -f -y 3 r4@0x10
'
```

Observed state machine:

- after short write `0x00`, `r4@0x10` returns `07 01 03 00`
- after short write `0x01`, `r4@0x10` returns `01 03 00 00`
- the same phase change is visible through byte/word helpers:
  - phase0: `reg00=0x07`, `reg21=0x07`, `reg30w=0x0107`
  - phase1: `reg00=0x01`, `reg21=0x01`, `reg30w=0x0301`
- this proves the chip is not a plain repeated-start register file; it has a
  command-style wake/prepare protocol

Working raw certificate extraction:

```sh
ssh root@172.16.42.77 '
  i2cset -f -y 3 0x10 0x00 >/dev/null 2>&1 || true
  i2cset -f -y 3 0x10 0x01 >/dev/null 2>&1 || true
  i2cset -f -y 3 0x10 0x31 >/dev/null 2>&1 || true
  for i in $(seq 1 38); do
    i2ctransfer -f -y 3 r16@0x10
  done
'
```

Observed certificate facts:

- the stream starts with `30 82 02 5b`, which is valid ASN.1 DER
- the dumped blob is 608 bytes long
- `openssl asn1parse -inform DER` recognizes it as PKCS#7 `signedData`
- this matches the old `nr5 / MFI_GET_RESPONSE` expectation from the reference
  spec

Current narrow blocker after the raw cert breakthrough:

- challenge writes do change the chip state, but the correct signature trigger
  is still unknown
- one repeated live result after challenge attempts was status `0x80`, while
  the expected 64-byte signature stream still stayed zero
- this means the frontier is now the challenge/signature command path, not bus
  discovery and not certificate retrieval
