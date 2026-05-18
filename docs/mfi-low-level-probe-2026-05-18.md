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

Useful disasm clues from the preserved kernel modules:

- `apple_mfi_auth_i2c_prepare` exists as a distinct step before the old kernel
  cert/sign helpers
- `apple_mfi_smbus_read_cert_len` and `apple_mfi_smbus_read_cert` both call
  `apple_mfi_auth_i2c_prepare(...)` and then sleep before reading
- the old ioctl path clearly writes the 32-byte challenge through command
  `0x4E`
- the old challenge path then polls command `0x10` and expects byte `0x10`
  before continuing

Live mismatch against that old sign-path expectation:

```sh
ssh root@172.16.42.77 '
  i2ctransfer -f -y 3 w33@0x10 \
    0x4e \
    0x00 0x01 0x02 0x03 0x04 0x05 0x06 0x07 \
    0x08 0x09 0x0a 0x0b 0x0c 0x0d 0x0e 0x0f \
    0x10 0x11 0x12 0x13 0x14 0x15 0x16 0x17 \
    0x18 0x19 0x1a 0x1b 0x1c 0x1d 0x1e 0x1f
  i2cset -f -y 3 0x10 0x10
  sleep 1
  i2ctransfer -f -y 3 w1@0x10 0x10 r1
'
```

Observed result:

- the challenge write does affect state
- after the later `0x10` trigger, the chip returns `0x80`
- `0x11` and `0x12` still read as zero-padded data instead of a 64-byte
  signature

Practical implication:

- the old kernel contract around signing was richer than "write `0x4E`, then
  read `0x12`"
- the remaining clean-room task is to recover that exact intermediate
  prepare/trigger/poll sequence

External working-case corrections gathered after the first raw sign attempts:

- one public reverse-engineering write-up for an Apple auth coprocessor shows
  the challenge path as:
  - write challenge to `0x21`
  - write start flag `0x01` to control/status `0x10`
  - poll `0x10` until it becomes `0x10`
  - read response length from `0x11`
  - read response bytes from `0x12`
- another public Linux+i2c-dev example for the same family uses the same ACP
  3.0 register map:
  - `0x10` control/status
  - `0x11` challenge response length
  - `0x12` challenge response data
  - `0x20` challenge data length
  - `0x21` challenge data
  - `0x4E` device certificate serial number

Why this matters for our clean-room track:

- our old local fallback code treated `0x4E` as the challenge write register
- that is very likely wrong for the ACP 3.0 style contract
- the live phase bytes we already saw (`07 01 03 00`) also fit ACP 3.0 much
  better than ACP 2.0C:
  - device version `0x07`
  - auth revision `0x01`
  - protocol major `0x03`
  - protocol minor `0x00`

Live result after switching to the corrected ACP 3.0 challenge map:

```sh
ssh root@172.16.42.77 '
  i2cset -f -y 3 0x10 0x00
  i2cset -f -y 3 0x10 0x01
  i2ctransfer -f -y 3 w33@0x10 0x21 ...32 challenge bytes...
  i2cset -f -y 3 0x10 0x10 0x01 b
  i2ctransfer -f -y 3 w1@0x10 0x10 r1
  i2ctransfer -f -y 3 w1@0x10 0x11 r2
  i2ctransfer -f -y 3 w1@0x10 0x12 r16
'
```

Observed result:

- the corrected contiguous write to `0x21` is accepted
- after `0x10=0x01`, the chip no longer goes to the older `0x80` state from
  the `0x4E` experiments
- instead, it stays at `0x00`, with `0x11 = 0x0000` and no signature bytes
- `error_code` at `0x05` also stays `0x00`

Current narrow conclusion:

- the register map is now much less ambiguous
- the remaining blocker is not "wrong register family" anymore
- it is the still-missing ACP 3.0 sign-side prepare/arming sequence before
  `0x10` starts producing `0x10` and valid `0x11/0x12` output

Final breakthrough from the plain `open/write/read` ACP3 transport:

```sh
/run/carthing-mfi-probe-test raw-sign \
  000102030405060708090a0b0c0d0e0f\
101112131415161718191a1b1c1d1e1f
```

Observed live result:

- `short write 0x01` may still NACK on this bus and is not required for success
- the critical steps are:
  - contiguous write `0x21 + 32 challenge bytes`
  - contiguous write `0x10 0x01`
  - poll through plain `write(reg) + read()` transport, not through the old
    repeated-start helper
- the real status sequence on the working image was:
  - `poll[1]=nack`
  - `poll[2]=nack`
  - `poll[3]=0x10`
- then:
  - `error-code=0x00`
  - `signature-len=0x0040`
  - full 64-byte signature returned successfully

Example live signature for challenge `00..1f`:

```text
0164d52a60fb39e316c1cbbe77fafaa7ad73b6b91f160437323674835d5157d5
42313191b26ad4ae1843949151fad417d86dc9f497a43dd563ad2374da3a12fc
```

Meaning:

- the sign path is now also proven on the live device
- the old local `0x4E -> 0x12` fallback was wrong for the active chip path
- the remaining work is no longer "can we talk to the auth chip at all?"
- it is now:
  - polish the helper
  - expose this as the clean-room auth backend
  - build our own higher MFi/iAP2 layer on top of the proven cert+sign path
