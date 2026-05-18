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

New reusable userspace building block:

- `carthing-mfi-probe aa03 <challenge_hex>`
- this command now:
  - signs through the proven raw ACP3 path on the live auth chip
  - wraps the 64-byte signature into a ready iAP2 control-session payload for
    `AA03 AuthenticationChallengeResponse`

Live proof:

- output length: `74` bytes
- first bytes:
  - `40 40` = iAP2 control-session start
  - `00 4a` = total CSM length
  - `aa 03` = `AuthenticationChallengeResponse`
  - `00 44 00 00` = param header for 64-byte signature

Example head from live `aa03` output:

```text
4040004aaa0300440000d63cd9ffb787b5780b9cac69cdfe...
```

Practical meaning:

- we no longer only have "raw cert bytes" and "raw signature bytes"
- we already have the first directly reusable iAP2 auth message builder for the
  new stack

Next clean-room auth milestone proven later on the same image:

- `aa01` no longer has to depend on an externally staged `pkcs7.bin`
- the helper can now extract PKCS#7 live from the auth chip and wrap it as
  `AA01`
- the helper can also answer `AA00` and `AA02` directly from stdin using only
  the live chip

New commands:

- `carthing-mfi-probe aa01-live`
- `carthing-mfi-probe auth-reply-live`
- `carthing-mfi-probe auth-loop-live`

Live proof:

```sh
/run/carthing-mfi-probe-test aa01-live | wc -c
printf '\x40\x40\x00\x06\xaa\x00' | \
  /run/carthing-mfi-probe-test auth-reply-live | wc -c
python3 make_aa02.py | /run/carthing-mfi-probe-test auth-reply-live | wc -c
```

Observed results:

- `aa01-live` returns `618` bytes, matching the known-good `AA01` envelope
- `auth-reply-live` on synthetic `AA00` also returns `618` bytes
- `auth-reply-live` on synthetic `AA02` returns `74` bytes and drives the live
  ACP3 sign path:
  - `poll[1]=nack`
  - `poll[2]=nack`
  - `poll[3]=0x10`
  - `error-code=0x00`
  - `signature-len=0x0040`

Meaning:

- the clean-room backend is no longer "file + helper"
- it is already a live iAP2 auth responder backed directly by the chip
- the next layer is now transport/session integration, not more auth-chip
  archaeology

Next session-layer milestone:

- a separate new binary now exists: `carthing-iap2-mini`
- it is not old Spotify userspace and not BlueZ glue
- it is only a tiny clean-room control/session layer on top of our own
  `carthing-mfi-probe`

What it does:

- forwards `AA00` to `carthing-mfi-probe aa01-live`
- forwards `AA02` to `carthing-mfi-probe aa03 <challenge>`
- remembers `AA05`
- answers `0x1D00 StartIdentification` with a minimal `0x1D01
  IdentificationInformation`

Current minimal IdentificationInformation policy:

- include only:
  - `0x0000` AccessoryName
  - `0x0001` ModelName
  - `0x0002` Manufacturer
  - `0x0003` SerialNumber
  - `0x0004` FirmwareVersion
  - `0x0005` HardwareVersion
  - `0x0006` empty
  - `0x0007` empty
  - `0x0008` PowerCapability
  - `0x0009` MaxCurrent
- omit:
  - `0x000A`
  - `0x000B`

Live proof:

```sh
printf '\x40\x40\x00\x06\xaa\x00' | \
  CARTHING_MFI_HELPER=/run/carthing-mfi-probe-test \
  /run/carthing-iap2-mini-test loop | wc -c
```

Observed result:

- `618`

Live `AA02` proof:

```text
[iap2-mini] <- AA02
poll[1]=nack
poll[2]=0x10
error-code=0x00
signature-len=0x0040
```

Observed result:

- output length `74`

Live `AA05 + 1D00` proof:

```text
[iap2-mini] <- AA05 auth success
[iap2-mini] <- 1D00 StartIdentification
40 40 00 75 1d 01 ...
```

Meaning:

- auth is no longer the only proven layer
- we now also have the first clean-room iAP2 control/session responder above it
- the next work frontier is transport integration and then `1D02/1D03`

Next transport milestone:

- `carthing-iap2-mini` now also speaks raw iAP2 `FF 5A` framing
- this is still not the old link-layer stack and not RFCOMM orchestration
- it is just the next clean-room transport step above the already proven
  control/session logic

New commands:

- `carthing-iap2-mini raw-loop`
- `carthing-iap2-mini identify-raw`

Live raw-iAP2 proof:

```sh
printf '\xff\x5a\x00\x06\xaa\x00' | \
  CARTHING_MFI_HELPER=/run/carthing-mfi-probe-test \
  /run/carthing-iap2-mini-test raw-loop | wc -c
```

Observed result:

- `618`

Live raw `AA02` proof:

```text
[iap2-mini] <- AA02
poll[1]=nack
poll[2]=0x10
error-code=0x00
signature-len=0x0040
```

Observed result:

- output length `74`

Live raw `AA05 + 1D00` proof:

```text
[iap2-mini] <- AA05 auth success
[iap2-mini] <- 1D00 StartIdentification
ff 5a 00 75 1d 01 ...
```

Meaning:

- we now have both:
  - bare control-session responder
  - raw iAP2 `FF 5A` responder
- the next real frontier is no longer auth or identification TLV shape
- it is full link-layer / real Bluetooth transport attachment

Next link-layer milestone:

- `carthing-iap2-mini` now also has `link-loop`
- this handles the minimal real iAP2 packet format:
  - `SYN`
  - `SYN+ACK`
  - `ACK`
  - control-session `DATA/ACK` on `sid=0`
- checksums are verified and responses are emitted as real iAP2 link packets,
  not just raw `FF 5A` messages

Synthetic live proof on the device:

1. Incoming `SYN`:

```text
[iap2-mini] <- link SYN ctl=0x80 seq=17
ff 5a 00 18 c0 00 11 00 ...
```

Meaning:

- the daemon accepts a real link-layer `SYN`
- it emits a real `SYN+ACK`

2. Incoming `SYN + AA00` stream:

```text
[iap2-mini] <- link SYN ctl=0x80 seq=17
[iap2-mini] <- link AA00
```

Observed result:

- total output `652` bytes
- head:

```text
ff5a0018c0001100...
ff5a027440011200...4040026aaa010264...
```

Meaning:

- packet 1 = `SYN+ACK`
- packet 2 = link-layer `ACK+DATA`
- payload inside packet 2 is a real `AA01`

3. Incoming `SYN + AA05 + 1D00` stream:

```text
[iap2-mini] <- link SYN ctl=0x80 seq=17
[iap2-mini] <- link AA05 auth success
[iap2-mini] <- link 1D00 StartIdentification
```

Observed result:

- total output `160` bytes
- head:

```text
ff5a0018c0001100...
ff5a000940011200...
ff5a007f40021300...404000751d01...
```

Meaning:

- packet 1 = `SYN+ACK`
- packet 2 = bare `ACK` for `AA05`
- packet 3 = link-layer `ACK+DATA`
- payload inside packet 3 is a real `1D01 IdentificationInformation`

Current frontier after this proof:

- auth backend is proven
- session layer is proven
- raw transport is proven
- link-layer framing is proven
- the next missing piece is only the real Bluetooth transport attachment to the
  iPhone path

## 2026-05-18: RFCOMM server wrapper proven around the new link layer

What changed:

- `carthing-iap2-mini` now also has `rfcomm-listen`
- this is not a new protocol layer; it is a narrow transport wrapper around the
  already-proven `link-loop`
- it binds an RFCOMM server socket on channel `3`, accepts one peer, then hands
  the accepted socket straight into the same minimal clean-room iAP2 link loop

Implementation notes:

- no BlueZ headers or runtime were added
- the wrapper uses raw Linux Bluetooth socket constants and a local
  `sockaddr_rc` definition
- channel is controlled by `CARTHING_IAP2_RFCOMM_CHANNEL`, default `3`
- `SIGPIPE` is ignored so a remote close does not kill the process before the
  iAP2 state machine can unwind cleanly

Live proof on the device:

- the rebuilt binary was copied to the target through plain `ssh + cat`
  because this minimal rootfs does not ship `sftp-server`
- on the real device the new binary printed:

```text
[iap2-mini] RFCOMM listen ch=3
```

Meaning:

- the current custom kernel/userspace can already host the local classic
  RFCOMM server endpoint we need for iAP2
- the new transport path is no longer blocked on auth, no longer blocked on
  control/session logic, and no longer blocked on iAP2 framing

Updated frontier after this proof:

- `carthing-mfi-probe` proves live cert/sign against the auth chip
- `carthing-iap2-mini link-loop` proves minimal real iAP2 framing
- `carthing-iap2-mini rfcomm-listen` proves the local RFCOMM server endpoint
- the next missing layer is now narrower:
  - BR/EDR discoverability/connectability policy
  - SDP exposure of the iAP2 service UUID and RFCOMM channel
  - then a real iPhone-initiated attach into this new daemon

## 2026-05-18: local L2CAP SDP socket path proven

What changed:

- `carthing-iap2-mini` now also has `sdp-listen`
- this does not implement SDP responses yet; it only proves that our new stack
  can host the local classic Bluetooth `L2CAP` endpoint for `PSM 0x0001`
  without any BlueZ userspace runtime

Implementation notes:

- the listener uses raw Linux Bluetooth socket constants and a local
  `sockaddr_l2` definition
- `CARTHING_IAP2_L2CAP_PSM` defaults to `0x0001`, the classic SDP PSM

Live proof on the device:

- the rebuilt target binary was pushed through `ssh + cat`
- on the real device the new binary printed:

```text
[iap2-mini] L2CAP listen psm=0x0001
```

Meaning:

- the current custom kernel/userspace can already host both local transport
  sockets that matter for the clean-room iAP2 path:
  - RFCOMM channel `3`
  - L2CAP PSM `0x0001`

Updated frontier after this proof:

- auth chip access is proven
- iAP2 control/session/link framing is proven
- RFCOMM server bind/listen is proven
- SDP L2CAP socket bind/listen is proven
- the next missing layer is now even narrower:
  - a minimal SDP responder / service-record exposure for the iAP2 UUID and
    RFCOMM channel
  - then real iPhone-initiated classic attach into `carthing-iap2-mini`

## 2026-05-18: minimal clean-room SDP responder proven

What changed:

- `carthing-iap2-mini` now also has `sdp-loop`
- `sdp-listen` is no longer only a passive bind/listen proof; it now runs the
  same responder over a real accepted `L2CAP PSM 0x0001` socket
- the responder is still intentionally minimal:
  - `ServiceSearchRequest`
  - `ServiceAttributeRequest`
  - `ServiceSearchAttributeRequest`
- it serves one clean-room service record for:
  - service UUID `00000000-deca-fade-deca-deafdecacaff`
  - RFCOMM channel `3`
  - service name `Wireless iAP`

Implemented record attributes:

- `0x0000` ServiceRecordHandle = `0x00010000`
- `0x0001` ServiceClassIDList = `caff`
- `0x0002` ServiceRecordState = `0`
- `0x0004` ProtocolDescriptorList = `L2CAP + RFCOMM ch 3`
- `0x0005` BrowseGroupList = `PublicBrowseGroup`
- `0x0006` LanguageBaseAttributeIDList
- `0x0008` ServiceAvailability = `0xff`
- `0x0009` BluetoothProfileDescriptorList
- `0x0100` ServiceName = `Wireless iAP`

Local synthetic proof on the host build:

1. `ServiceSearchRequest` for `caff`

Observed response:

```text
03 00 01 00 09 00 01 00 01 00 01 00 00 00 00
```

Meaning:

- one matching service exists
- handle returned is `0x00010000`

2. `ServiceSearchAttributeRequest` for `caff` with attr range `0x0000-0xffff`

Observed response head:

```text
07 00 02 00 92 00 8f 35 8d 35 8b 09 00 00 0a 00 01 00 00 ...
```

Meaning:

- response PDU is correct `0x07`
- returned attribute list contains the clean-room record with our handle,
  `caff`, and RFCOMM channel `3`

3. `ServiceAttributeRequest` for handle `0x00010000`

Observed response head:

```text
05 00 03 00 90 00 8d 35 8b 09 00 00 0a 00 01 00 00 ...
```

Meaning:

- handle lookup by attribute request also works

Live proof on the real device:

- the rebuilt target binary was pushed to `/run/carthing-iap2-mini-test`
- `sdp-loop` on the target returned the same `ServiceSearchAttributeResponse`
  bytes for the synthetic `caff` query:

```text
07 00 02 00 92 00 8f 35 8d 35 8b 09 00 00 0a 00 01 00 00 ...
```

Updated frontier after this proof:

- auth backend is proven
- iAP2 control/session/link layer is proven
- local RFCOMM server endpoint is proven
- local SDP socket endpoint is proven
- minimal SDP responder is proven
- the next missing layer is no longer SDP syntax; it is now:
  - BR/EDR discoverability/connectability policy
  - real iPhone-initiated classic attach into this new RFCOMM+iAP2 daemon

## 2026-05-18: BR/EDR scan policy proven and transport daemon brought up

What changed:

- `carthing-iap2-mini` now also has:
  - `hci-read-scan`
  - `hci-write-scan`
  - `transport-daemon`
- these modes are still clean-room and do not pull back BlueZ userspace
- they use raw `HCI` sockets plus the already proven local transport pieces

Live HCI facts on the real device:

1. Before any change, classic scan policy was off:

```text
[iap2-mini] HCI scan enable=0x00
0x00
```

Meaning:

- the previous classic transport frontier was blocked lower than SDP
- BR/EDR discoverability/connectability was simply disabled on the controller

2. Writing `both` and reading it back now works:

```text
[iap2-mini] HCI wrote scan enable=0x03
[iap2-mini] HCI scan enable=0x03
0x03
```

Meaning:

- our new stack can now explicitly enable both inquiry scan and page scan
- the clean-room path is no longer blocked on hidden controller policy

3. The combined transport daemon was then started live on the device:

```text
[iap2-mini] HCI wrote scan enable=0x03
[iap2-mini] transport daemon up: scan=0x03 sdp_psm=0x0001 rfcomm_ch=3
[iap2-mini] RFCOMM listen ch=3
[iap2-mini] L2CAP listen psm=0x0001
```

Meaning:

- the new clean-room classic path is now alive as one coherent runtime:
  - BR/EDR scans enabled
  - SDP responder listening on `PSM 0x0001`
  - iAP2 RFCOMM endpoint listening on channel `3`

Updated frontier after this proof:

- auth chip backend is proven
- iAP2 control/session/link layer is proven
- minimal SDP responder is proven
- BR/EDR scan policy is proven and controllable
- transport daemon is live
- the next missing step is finally the first real external classic attach from
  the iPhone into this new stack

## 2026-05-18: classic identity frontier narrowed to CoD and fixed live

What changed:

- `carthing-iap2-mini` now also has:
  - `hci-read-bdaddr`
  - `hci-read-name`
  - `hci-write-name`
  - `hci-read-class`
  - `hci-write-class`
- `transport-daemon` now sets a default `Class of Device` before enabling
  classic scans

Live controller identity on the real device before the fix:

```text
[iap2-mini] HCI bdaddr=30:E3:D6:04:C3:42
30:E3:D6:04:C3:42
[iap2-mini] HCI local name len=14
Car Thing-0346
[iap2-mini] HCI class of device=0x000000
0x000000
```

Meaning:

- local classic address is stable and readable
- local classic name is not empty
- but `Class of Device` was completely unset

This matters because a working external iAP case explicitly notes that Apple
visibility on classic Bluetooth depends on CoD being set to an Apple-friendly
device class, and lists `Car Audio = 0x240420` as one valid value for
`Wireless iAP` visibility.

Live fix:

```text
[iap2-mini] HCI wrote class of device=0x240420
[iap2-mini] HCI class of device=0x240420
0x240420
```

Then the transport daemon was restarted with that default:

```text
[iap2-mini] HCI wrote class of device=0x240420
[iap2-mini] HCI wrote scan enable=0x03
[iap2-mini] transport daemon up: class=0x240420 scan=0x03 sdp_psm=0x0001 rfcomm_ch=3
[iap2-mini] RFCOMM listen ch=3
[iap2-mini] L2CAP listen psm=0x0001
```

Updated frontier after this proof:

- auth backend is proven
- iAP2 control/session/link layer is proven
- SDP responder is proven
- BR/EDR scan policy is proven
- classic CoD is now explicitly set to `0x240420`
- the next missing step is now the real external iPhone attach into this live
  classic path

## 2026-05-18: classic iAP2 transport now carries EIR, SSP event mask, and socket security

What changed in the clean-room daemon:

- `transport-daemon` now also writes:
  - `Inquiry Mode = 0x02` (extended inquiry)
  - an `EIR` block with the local name and `CAFF`
  - the controller event mask before the SSP loop starts
- the local classic sockets now request `BT_SECURITY_HIGH` on:
  - RFCOMM listen/accepted sockets
  - L2CAP listen/accepted sockets

Live startup proof on the real device:

```text
[iap2-mini] HCI wrote class of device=0x240420
[iap2-mini] HCI wrote inquiry mode=0x02
[iap2-mini] HCI wrote EIR name=Car Thing-0346 uuid=caff
[iap2-mini] HCI wrote event mask=3fffffffffffffff
[iap2-mini] HCI wrote simple pairing mode=1
[iap2-mini] HCI wrote scan enable=0x03
[iap2-mini] transport daemon up: class=0x240420 scan=0x03 ssp=on sdp_psm=0x0001 rfcomm_ch=3
[iap2-mini] RFCOMM listen BT_SECURITY_HIGH set
[iap2-mini] RFCOMM listen ch=3
[iap2-mini] L2CAP listen BT_SECURITY_HIGH set
[iap2-mini] L2CAP listen psm=0x0001
[iap2-mini] SSP agent listening on hci0
```

This proves the controller-side classic identity is now much closer to the
old working MFi Bluetooth contract than the first raw RFCOMM experiments were.

## 2026-05-18: user-facing iPhone Settings pairing is a HID contract, not the raw iAP2 transport

The old preserved notes were the decisive clue here.

When the iPhone shows:

```text
Pairing Unsuccessful
Not Supported
```

that is not the same failure mode as "RF transport is dead" or "SSP is broken".
It means the iPhone saw the accessory, but rejected the advertised accessory
contract before it ever attached to the new clean-room iAP2 transport.

The preserved working notes point to a strict separation:

- the user-facing Settings pairing flow belongs to the HID identity
- the old "not supported" failure appeared when Car Thing looked like
  phone/audio/MFi instead of HID
- the clean-room classic iAP2 path is therefore not a drop-in replacement for
  the HID pairing identity in the iPhone Bluetooth UI

This matches the live evidence from the new daemon:

- after repeated `Not Supported` failures, there were still no incoming
  `SSP`, `L2CAP accepted`, or `RFCOMM accepted` lines
- meaning the iPhone rejected the accessory before entering the raw classic
  transport we built

So the boundary is now explicit:

- keep the proven BLE HID runtime as the user-facing pairing path
- keep `carthing-iap2-mini` as a separate clean-room MFi/iAP2 transport track
- do not treat a Bluetooth Settings pair attempt as the main validation path for
  the raw classic iAP2 daemon

Updated frontier after this correction:

- low-level MFi auth is proven
- iAP2 control/session/link/RFCOMM/SDP are proven locally
- controller identity, EIR, SSP, and socket security are proven locally
- but the clean-room daemon still lacks the higher external contract that made
  the old classic path acceptable to iPhone
- the next meaningful iAP2 step is no longer "more CoD/SSP tweaks", but the
  higher-profile `CAFE` / reconnect / profile-semantics layer from the old
  working reference

## 2026-05-18: first clean-room `CAFE` active-connect path added

The next layer from the old working reference is now represented directly in
the new codebase.

`carthing-iap2-mini` now has a new command:

```text
carthing-iap2-mini cafe-connect <AA:BB:CC:DD:EE:FF>
```

What it does:

- connects to the peer over SDP (`L2CAP PSM 0x0001`)
- sends a `ServiceSearchAttributeRequest` for the `CAFE` UUID
- extracts the peer RFCOMM channel from `ProtocolDescriptorList`
- falls back to `CAFF`, then finally to channel `1`
- opens an outbound RFCOMM client socket
- enters client-mode iAP2 link bring-up by sending the initial `SYN`

This is the first clean-room equivalent of the old `active connect` fallback
logic. It does not reintroduce BlueZ profile registration; it only adds the
outbound `CAFE` discovery/connect leg that was missing from the raw server-only
experiments.

Status:

- both host and target builds pass with this new mode
- no live iPhone-side proof yet in this turn
- the next step is to feed it a real peer BD_ADDR from the already working
  HID-paired phone and observe whether the iPhone exposes `CAFE` at all
