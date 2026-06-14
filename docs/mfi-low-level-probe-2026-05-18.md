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

Classic transport checkpoint collected later on the same working image:

```sh
ssh root@172.16.42.77 '
  /run/carthing-iap2-inquiry-test hci-inquiry
  /run/carthing-iap2-inquiry-test hci-remote-name 10:A2:D3:83:82:50
'
```

Observed result:

- classic inquiry does see the iPhone as:
  - `10:A2:D3:83:82:50 cod=0x7a020c rssi=-35 name=iPhone`
- `Remote Name Request` to that address succeeds
- outbound `L2CAP`/`RFCOMM` active-connect from our clean-room `CAFE` path still
  fails with `No route to host`

Practical implication:

- the iPhone is visible to classic inquiry and paging
- the current blocker is narrower than discovery
- the next missing piece on the clean-room iAP2 side is not `CoD`, not `EIR`,
  and not name discovery; it is the active classic attach contract that the old
  `CAFE`/profile path used after discovery
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

## 2026-05-19: classic ACL bring-up is now proven, `No route to host` moved above raw link creation

The next clean-room missing layer turned out to be lower than SDP/RFCOMM
discovery, but higher than the controller identity work.

`carthing-iap2-mini` now explicitly creates a classic ACL link before trying
`SDP` or outbound `RFCOMM`:

```text
carthing-iap2-mini hci-create-acl <AA:BB:CC:DD:EE:FF>
carthing-iap2-mini cafe-connect <AA:BB:CC:DD:EE:FF>
```

`cafe-connect` now does this by default unless
`CARTHING_IAP2_SKIP_ACL_CREATE=1` is set.

Live proof on the device against the real iPhone classic address:

```text
[iap2-mini] HCI remote name request peer=10:A2:D3:83:82:50
iPhone
[iap2-mini] HCI create ACL started peer=10:A2:D3:83:82:50
[iap2-mini] HCI ACL up peer=10:A2:D3:83:82:50 handle=0x000c link_type=0x01
```

After that, outbound sockets still fail:

```text
[iap2-mini] L2CAP connect peer=10:A2:D3:83:82:50 psm=0x0001
connect(L2CAP client): No route to host
[iap2-mini] RFCOMM connect peer=10:A2:D3:83:82:50 ch=1
connect(RFCOMM client): No route to host
```

The client sockets were then upgraded to `BT_SECURITY_HIGH`, but the result
did not change.

This narrows the frontier sharply:

- the real iPhone classic `BD_ADDR` is known and live
- raw classic ACL creation is proven
- the old `No route to host` is no longer explained by "no classic link"
- the blocker is now above ACL creation and below successful `SDP/RFCOMM`
  attachment

So the next layer to investigate is no longer basic HCI reachability, but the
classic attach contract itself: service availability, authorization, or iPhone
policy on top of an already-up ACL.

## 2026-05-19: peer-side disconnect reason after classic attach attempts

The next live probe added a short HCI peer-watch around `cafe-connect`.

That produced the first concrete post-ACL failure reason:

```text
[iap2-mini] HCI ACL up peer=10:A2:D3:83:82:50 handle=0x000c link_type=0x01
[iap2-mini] L2CAP connect peer=10:A2:D3:83:82:50 psm=0x0001
connect(L2CAP client): No route to host
[iap2-mini] RFCOMM connect peer=10:A2:D3:83:82:50 ch=1
connect(RFCOMM client): No route to host
[iap2-mini] peer-watch DISCONN_COMPLETE handle=0x000c status=0x00 reason=0x14
```

`0x14` is the standard HCI disconnect reason
`Remote Device Terminated Connection Due To Low Resources`.

In practical terms for this project, the key point is not the wording itself,
but that the disconnect now clearly comes from the iPhone side after our
outbound classic attach attempts, not from an inability to establish the ACL.

That means the new frontier is even narrower:

- classic discovery and the iPhone classic address are real
- classic ACL creation is real
- iPhone is the side terminating the link after attach attempts
- the remaining blocker is therefore in the higher classic attach contract
  above raw ACL creation and below a successful iAP2 `SDP/RFCOMM` session

## 2026-05-19: `transport-active` proved classic auth is now the blocker, not reachability

The next meaningful upgrade was to stop testing outbound `CAFE` in isolation
and instead run it together with the clean-room server-side classic transport:

- `HCIDEVUP` support was added so `carthing-iap2-mini` can bring `hci0` up by
  itself after the BLE runtime is stopped
- a new mode was added:

```text
carthing-iap2-mini transport-active <AA:BB:CC:DD:EE:FF>
```

This mode now does all of the following in one process:

- bring `hci0` up
- set `CoD`, `EIR`, `event mask`, `SSP`, and `scan enable`
- start the clean-room `SSP` agent
- start local `SDP` and `RFCOMM` listeners
- then run outbound `CAFE`/`CAFF` attach attempts to the peer

Live result against the real iPhone classic address:

```text
[iap2-mini] HCI dev hci0 up
[iap2-mini] transport-active up: class=0x240420 scan=0x03 ssp=on sdp_psm=0x0001 rfcomm_ch=3 peer=10:A2:D3:83:82:50
[iap2-mini] HCI ACL up peer=10:A2:D3:83:82:50 handle=0x000c link_type=0x01
[iap2-mini] SSP LINK_KEY_REQ from 10:A2:D3:83:82:50 -> negative
[iap2-mini] SSP IO_CAP_REQ from 10:A2:D3:83:82:50
[iap2-mini] SSP USER_CONFIRM_REQ from 10:A2:D3:83:82:50
[iap2-mini] SSP COMPLETE status=0x05 peer=10:A2:D3:83:82:50
[iap2-mini] AUTH COMPLETE status=0x05 handle=0x000c
connect(L2CAP client): Connection refused
...
connect(RFCOMM client): Connection refused
[iap2-mini] peer-watch DISCONN_COMPLETE handle=0x000c status=0x00 reason=0x16
```

This is a major narrowing step:

- the old `Network is down` condition is gone
- the old `No route to host` condition is gone in this integrated mode
- the iPhone and Car Thing do reach the classic auth phase
- the current blocker is now classic authentication / pairing policy itself

In other words, the next step is no longer "make the transport exist" but
"understand why classic auth ends with status `0x05` and a refused attach".

User-facing confirmation from the same frontier:

- the test persona appears in iPhone Bluetooth UI as a distinct device:
  - `CarThing iAP2`
- attempting to pair that persona from iPhone produces the standard failure UI:
  - "Pairing Unsuccessful"
  - "Make sure CarThing iAP2 is turned on, in range, and is ready to pair"
- this confirms the failure is not just an internal accessory-side log artifact;
  iOS also treats the classic pairing attempt as unsuccessful
- after the failed attempt:
  - no new BR/EDR link key is persisted into `iap2-link-keys.txt`
  - the normal BLE/HID identity (`CarThing`) remains a separate trusted path and
    must not be conflated with the temporary classic/iAP2 persona during tests

## 2026-05-21: `DisplayYesNo + MITM` unlocked successful classic pairing, and MFi auth now reaches IdentificationAccepted

The next two live passes moved the frontier far beyond the earlier SSP failure.

First change:

- the temporary classic persona was changed from:
  - `NoInputNoOutput + GeneralBondingNoMITM`
- to:
  - `DisplayYesNo + GeneralBondingMITM`

User-visible result:

- pairing for `CarThing iAP2` no longer failed immediately
- iPhone showed:
  - the pairing prompt
  - a pairing code
  - the follow-up trust/allow dialog
- after confirmation, `CarThing iAP2` moved into trusted devices

Accessory-side proof from the same run:

- `LINK_KEY_REQ -> negative`
- `IO_CAP_RSP ... io=0x01 auth=0x05`
- `SIMPLE_PAIRING_COMPLETE status=0x00`
- `LINK_KEY_NOTIFY ... type=0x05`
- `AUTH COMPLETE status=0x00`
- a new classic link key was persisted into:
  - `/run/carthing-state/carthing/iap2-link-keys.txt`

This means:

1. The old blocker was indeed SSP policy, not transport.
2. The previous `NoInputNoOutput + NoMITM` posture was too weak or too mismatched
   for the iPhone's policy for this persona.
3. The current working classic pairing posture is:
   - `DisplayYesNo`
   - `MITM`
   - saved BR/EDR link key type `0x05`

Second change:

- the missing helper `/usr/bin/carthing-mfi-probe` was supplied explicitly as:
  - `CARTHING_MFI_HELPER=/run/carthing-mfi-probe`

Live result after pairing was already established:

- `transport-active` reused the cached BR/EDR key successfully
- iAP2 auth progressed past both MFi steps:
  - `AA00` auth certificate request
  - `AA02` challenge request
  - `AA05` auth success
- identification then completed too:
  - `1D00 StartIdentification`
  - accessory sent `1D01`
  - iPhone answered `1D02 IdentificationAccepted`
- after that the accessory sent:
  - `0x6800` (Start HID)
  - `0x40C8` (Start NowPlaying)

Practical consequence:

1. The project now has a proven live path for all of the following on the same
   temporary classic persona:
   - classic pair
   - BR/EDR link key persistence
   - MFi auth chip interaction
   - iAP2 authentication success
   - identification acceptance by iPhone
2. The frontier is no longer "can we pair?" and no longer "can we authenticate?"
3. The next frontier is post-identification behavior:
   - confirm what the non-control link packets after `0x6800` / `0x40C8` mean
   - determine whether EA / HID / NowPlaying sessions are actually coming up
   - map which higher-level iPhone services become available on this live path

## 2026-05-19: classic test identity normalized to avoid duplicate trusted devices on iPhone

One practical side effect of the early classic experiments was that the clean-room
daemon exposed itself as `Car Thing-0346` while the normal BLE/HID runtime stayed
visible as `CarThing`.

That created an unwanted user-facing split on iPhone:

- `CarThing`
- `Car Thing-0346`

To stop polluting the trusted-device list, the clean-room classic path now uses
the same visible name as the working BLE/HID runtime:

- default classic local name: `CarThing`
- default classic EIR name: `CarThing`

So future integrated classic tests should no longer create an obviously separate
human-facing Bluetooth identity just because the transport path is different.

## 2026-05-20: inbound RFCOMM needed accessory-side link SYN before the iPhone would start real iAP2

The previous inbound server-side narrowing step had already shown:

- the iPhone trusted the accessory with a cached BR/EDR link key
- classic auth completed with `AUTH COMPLETE status=0x00`
- inbound `SDP` browse progressed once the responder matched the iPhone's initial
  `0x0100` search
- inbound `RFCOMM accepted` was reachable

But the session still looked stalled after `RFCOMM accepted`.

The next isolated experiment kept the same throwaway `0x0100`-compatible `SDP`
responder and changed exactly one more thing outside the working tree:

- after inbound `RFCOMM accepted`, run the link loop in initiator mode so the
  accessory sends the first link-layer `SYN`

That immediately produced a full live inbound iAP2 session:

```text
[iap2-mini] RFCOMM accepted peer=10:A2:D3:83:82:50 ch=3
[iap2-mini] -> link SYN (client mode)
[iap2-mini] <- link SYN ctl=0xc0 seq=181
[iap2-mini] adopting control sid=1 from first payload packet
[iap2-mini] <- link ctrl seq=182 sid=1 msg=0xaa00 len=6
[iap2-mini] <- link AA00
[iap2-mini] -> link 0xaa00 seq=1 sid=1 len=618
[iap2-mini] <- link ctrl seq=183 sid=1 msg=0xaa02 len=42
[iap2-mini] <- link AA02
[iap2-mini] -> link 0xaa02 seq=2 sid=1 len=74
[iap2-mini] <- link ctrl seq=184 sid=1 msg=0xaa05 len=6
[iap2-mini] <- link AA05 auth success
[iap2-mini] <- link ctrl seq=185 sid=1 msg=0x1d00 len=6
[iap2-mini] <- link 1D00 StartIdentification
[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=169
[iap2-mini] <- link ctrl seq=186 sid=1 msg=0x1d02 len=6
[iap2-mini] <- link 1D02 IdentificationAccepted
[iap2-mini] -> link 0x6800 seq=4 sid=1 len=39
[iap2-mini] -> link 0x40c8 seq=5 sid=1 len=42
```

This is the new high-value conclusion:

- inbound server-side iAP2 was not blocked at auth anymore
- inbound server-side iAP2 was not blocked at `SDP` anymore
- after inbound `RFCOMM accepted`, the iPhone was effectively waiting for the
  accessory to start the link session with `SYN`

So the inbound frontier narrowed from "why does nothing happen after tap?" to a
much more precise rule:

- server-side classic attach needs
  1. compatible initial `SDP` browse behavior
  2. accessory-side link-layer session start after `RFCOMM accepted`

This also explains why the previous server-only run stopped at `RFCOMM accepted`
with no further log traffic: the clean-room daemon was silently waiting for peer
bytes instead of starting the link session itself.

## 2026-05-20: even on the now-working inbound path, Apple Music still gave no useful NowPlaying traffic

Once the inbound link-layer session came up, a manual Apple Music `play/pause`
action was repeated while the device stayed connected.

Result:

- no additional inbound iAP2 control messages appeared
- no `0x4800 NowPlayingUpdate` appeared

So the earlier conclusion still holds on the inbound path too:

- `StartNowPlayingUpdates (0x40C8)` can be sent successfully
- Apple Music still does not produce useful `0x4800` metadata traffic here

## 2026-05-20: outbound `0x6801` HID mode1 was transmitted cleanly on the inbound session, but had no visible Apple Music effect

The next throwaway experiment extended the successful inbound setup with one more
post-identification action:

- after `1D02`, automatically send `0x6801 AccessoryHIDReport`
  `Play/Pause (0x00CD)` press + release in the simple mode1 format
  (big-endian, no report ID)

Live log:

```text
[iap2-mini] <- link 1D02 IdentificationAccepted
[iap2-mini] -> link 0x6800 seq=4 sid=1 len=39
[iap2-mini] -> link 0x40c8 seq=5 sid=1 len=42
[iap2-mini] -> link 0x6801 playpause press seq=6 sid=1 len=18
[iap2-mini] -> link 0x6801 playpause release seq=7 sid=1 len=18
```

User-visible result:

- Apple Music did not visibly toggle play/pause

This is consistent with the preserved notes that already warned:

- `0x00CD` via the basic HID mode can be transmitted and ACKed without causing
  real media control behavior

Practical conclusion for another agent:

1. The inbound iAP2 path is now good enough to reach live post-identification
   experiments, provided the accessory starts the link layer with `SYN`.
2. Apple Music metadata should still not be treated as an iAP2 `0x4800` target.
3. If iAP2 HID control is still desired, the next reasonable experiment is a
   format sweep over alternative HID wire encodings (`mode2`, `mode5`, `mode6`,
   and possibly legacy `0x6802`), not a re-investigation of auth or `SDP`.

## 2026-05-20: the broader iAP2 HID wire-format sweep still produced no visible Apple Music control

The earlier mode1 result could still have been explained by the wrong HID wire
encoding, so the next live cycle explicitly tested the remaining materially
different iAP2 HID variants on the same now-working inbound session model:

- foreground Apple Music was used during retests so Bluetooth Settings would not
  be the active UI
- each run still used the same proven prerequisites:
  - inbound `SDP` compatibility for the iPhone's initial `0x0100` search
  - accessory-side link `SYN` after `RFCOMM accepted`
  - successful `AA00 -> AA02 -> AA05 -> 1D00 -> 1D02`

Tested variants:

1. `mode6` — `0x6801`, report ID `0x01`, little-endian usage
2. `mode2` — `0x6801`, report ID `0x02`, big-endian usage
3. `mode5` — `0x6801`, no report ID, little-endian usage
4. `mode3` — legacy `0x6802`, big-endian usage

All of them were transmitted successfully on live accepted sessions. Example log
shapes:

```text
[iap2-mini] -> link 0x6801 mode6 playpause press seq=6 sid=1 len=19
[iap2-mini] -> link 0x6801 mode6 playpause release seq=7 sid=1 len=19

[iap2-mini] -> link 0x6801 mode2 playpause press seq=6 sid=1 len=19
[iap2-mini] -> link 0x6801 mode2 playpause release seq=7 sid=1 len=19

[iap2-mini] -> link 0x6801 mode5 playpause press seq=6 sid=1 len=18
[iap2-mini] -> link 0x6801 mode5 playpause release seq=7 sid=1 len=18

[iap2-mini] -> link 0x6802 mode3 playpause press seq=6 sid=1 len=18
[iap2-mini] -> link 0x6802 mode3 playpause release seq=7 sid=1 len=18
```

User-visible result for all tested variants:

- Apple Music did not visibly toggle play/pause

This materially strengthens the earlier conclusion:

- the problem is no longer "maybe the HID bytes are encoded wrong in an obvious
  way"
- a broad sweep across the practical iAP2 HID packet variants still did not
  yield usable Apple Music control on this path

So the research frontier should now move accordingly:

1. Stop treating iAP2 HID media control as the most likely near-term path for
   Apple Music play/pause on this device.
2. Keep the now-proven inbound iAP2 attach/session work as infrastructure.
3. Shift the next active search toward other control channels such as AVRCP or
   EA-specific behaviors, rather than repeating more iAP2 HID packet variants.

## 2026-05-20: fresh semantic HID sweep also produced no visible Apple Music effect

To avoid overfitting to prior notes, the next live cycle was rerun as a broader
semantic experiment instead of another simple packet-wrapper variant.

The sweep used:

- the same now-proven inbound iAP2 session model
  - `0x0100`-compatible inbound `SDP`
  - accessory-side link `SYN` after `RFCOMM accepted`
  - successful `AA00 -> AA02 -> AA05 -> 1D00 -> 1D02`
- authoritative USB HID Consumer usages rather than only the earlier
  `Play/Pause (0x00CD)` assumption
- longer press timing instead of near-immediate press/release

Commands sent on one accepted session:

1. `0x00B5` — Next Track
2. `0x00B6` — Previous Track
3. `0x00E9` — Volume Increment
4. `0x00EA` — Volume Decrement
5. `0x00B0` — Play
6. `0x00B1` — Pause
7. `0x00CD` — Play/Pause

Live log excerpt:

```text
[iap2-mini] -> link 0x6801 mode1 next-track press usage=0x00b5 seq=6 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 next-track release usage=0x00b5 seq=7 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 previous-track press usage=0x00b6 seq=8 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 previous-track release usage=0x00b6 seq=9 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 volume-up press usage=0x00e9 seq=10 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 volume-up release usage=0x00e9 seq=11 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 volume-down press usage=0x00ea seq=12 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 volume-down release usage=0x00ea seq=13 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 play press usage=0x00b0 seq=14 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 play release usage=0x00b0 seq=15 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 pause press usage=0x00b1 seq=16 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 pause release usage=0x00b1 seq=17 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 play-pause press usage=0x00cd seq=18 sid=1 len=18
[iap2-mini] -> link 0x6801 mode1 play-pause release usage=0x00cd seq=19 sid=1 len=18
```

User-visible result:

- Apple Music did not visibly react to any command in the sequence

This is stronger than the earlier narrow `0x00CD` result:

- not only the old `Play/Pause` packet
- not only one wire encoding
- not only one foreground/background state

Within the current iAP2 control-session model, a broader HID semantic sweep
still produced no usable Apple Music control.

Practical meaning:

1. The research should not keep assuming that "the next HID usage code" is the
   likely missing piece.
2. The proven value of the current work is the inbound iAP2 session contract
   itself, not successful Apple Music control through iAP2 HID.
3. The next broad MFi frontier should move toward EA session behavior, app
   launch, and other post-identification capabilities that are actually specific
   to MFi/iAP2, rather than looping on more HID media-control permutations.

## 2026-05-20: autonomous system events need to be treated as a separate frontier from generic iAP2 control

The next clarification was architectural, not just packet-level:

- companion app is explicitly out of scope
- the device must stay self-sufficient
- so any valuable iPhone-side events must come from system-exposed behavior that
  the accessory can consume on its own

That changes how the MFi/iAP2 layer should be interpreted.

Working conclusion:

1. A generic accepted iAP2 control session should **not** be treated as proof
   that notifications, battery state, or network status are available there.
2. Without a companion app, those iPhone-side signals should be treated as a
   distinct research frontier with their own protocol candidates.
3. For notifications specifically, the more realistic autonomous candidate is
   likely `ANCS` over BLE rather than generic iAP2 control-session traffic.
4. For other self-contained scenarios, the remaining high-value MFi-specific
   search area is post-identification behavior that iOS itself may expose
   without custom app logic: built-in profile interactions, EA/session
   negotiation, app-launch semantics, and other system-owned accessory flows.

Practical rule for future agents:

- Do not drift back into companion-app reasoning.
- Do not assume that iAP2 auth + `1D02` implies access to arbitrary iPhone
  telemetry.
- Treat autonomous notifications/system-state access as a separate protocol hunt.

## 2026-05-20: inbound classic attach was blocked by the initial SDP search contract, not by trust or auth

The next live narrowing step used the second device in a pure server-side mode.
Before this test, the clean-room daemon already had:

- a real cached BR/EDR link key for the iPhone
- successful `AUTH COMPLETE status=0x00`
- incoming `L2CAP` + `SDP SERVICE_SEARCH_REQUEST`

But the attach still appeared stuck from the iPhone UI point of view.

The key new observation was that the iPhone's first inbound `SDP` browse was:

```text
[iap2-mini] SDP rx params len=8 preview=35 03 19 01 00 00 30 00
```

That is, the first inbound `ServiceSearchRequest` asked for UUID `0x0100`.

At that moment, the current responder only treated the following as a positive
match:

- `0x1002`
- `CAFF`

So the clean-room daemon was returning an effectively empty result to the
iPhone's initial browse step, even though trust and classic authentication were
already working.

To isolate this, a temporary throwaway build was made outside the working tree,
with exactly one narrow behavior change:

- allow `sdp_pattern_matches_service(...)` to match `0x0100` as well

That one change produced an immediate user-visible difference on iPhone:

- tapping the trusted `CarThing Test iAP2` device now connected immediately

And the wire-level sequence advanced to:

```text
[iap2-mini] L2CAP accepted peer=10:A2:D3:83:82:50 psm=0x0001 cid=0x1c14
[iap2-mini] SSP LINK_KEY_REQ from 10:A2:D3:83:82:50 -> cached reply type=0x04
[iap2-mini] SDP rx hdr pdu=0x02(SERVICE_SEARCH_REQUEST) txn=0x0001 param_len=8
[iap2-mini] SDP rx params len=8 preview=35 03 19 01 00 00 30 00
[iap2-mini] AUTH COMPLETE status=0x00 handle=0x000b
[iap2-mini] SDP tx ok pdu=0x02(SERVICE_SEARCH_REQUEST) txn=0x0001
[iap2-mini] SDP rx hdr pdu=0x04(SERVICE_ATTRIBUTE_REQUEST) txn=0x0002 param_len=14
[iap2-mini] SDP rx params len=14 preview=00 01 00 00 01 00 35 05 0a 00 00 ff ff 00
[iap2-mini] SDP tx ok pdu=0x04(SERVICE_ATTRIBUTE_REQUEST) txn=0x0002
[iap2-mini] SDP rx hdr pdu=0x02(SERVICE_SEARCH_REQUEST) txn=0x0003 param_len=8
[iap2-mini] SDP rx params len=8 preview=35 03 19 12 00 00 30 00
[iap2-mini] SDP tx ok pdu=0x02(SERVICE_SEARCH_REQUEST) txn=0x0003
[iap2-mini] RFCOMM accepted peer=10:A2:D3:83:82:50 ch=3
```

This is a major frontier update:

- inbound classic attach is now proven to depend on the initial server-side SDP
  browse contract
- the previous "tap does nothing" behavior was not a trust failure anymore
- the previous "tap does nothing" behavior was not an MFi auth-chip problem
- matching the iPhone's first `0x0100` search is sufficient to move the peer to:
  - `ServiceAttributeRequest`
  - an additional `ServiceSearchRequest` for `0x1200`
  - inbound `RFCOMM` connection acceptance on channel `3`

Just as important, after `RFCOMM accepted`, no iAP2 payload was logged yet.
So the next unresolved frontier is narrower still:

- initial inbound browse problem: now localized
- next question: what exact post-`RFCOMM accepted` behavior causes the peer to
  remain quiet

Practical handoff conclusion for another agent:

1. Do not keep investigating inbound server-side attach as a trust or auth issue.
2. The first required fix is in the SDP responder contract, specifically the
   initial browse/search semantics seen from iPhone.
3. The next diagnostic step after promoting this behavior into the real code is
   to log the first post-accept RFCOMM/iAP2 bytes and determine whether the
   iPhone expects the accessory to speak first on this path.

## 2026-05-20: first ANCS notification mirror layer landed in the BLE runtime

The notification frontier has now moved from theory into the working tree.

What was added:

- new runtime module: `overlay/usr/lib/carthing/ancs_client.py`
- shared GATT client reuse so `AMS` and `ANCS` can coexist on the same encrypted
  iPhone connection
- `media_remote.py` now starts `ANCS` alongside `AMS` after pairing/encryption
- `now_playing_ui.py` now has a notification render path that can temporarily
  overlay the latest mirrored notification and then return to now-playing

Implemented ANCS behavior:

- discover the Apple Notification Center Service after the existing BLE/HID
  pairing flow is up
- subscribe to:
  - Notification Source
  - Data Source
- request notification attributes for new events:
  - app identifier
  - title
  - subtitle
  - message
- parse the returned ANCS attribute stream into a displayable notification model
- clear the on-screen overlay on timeout or explicit ANCS removal

Architectural meaning:

- the project already had the right base for this because `ams_client.py` had
  already proven iPhone-facing GATT discovery/subscribe/write on the same
  Bumble-based runtime
- notifications are now treated as a BLE/ANCS layer in the real userspace
  runtime, not as a speculative generic iAP2 control-session feature
- this keeps the implementation aligned with the explicit no-companion-app rule:
  use system-exposed iPhone behavior, not custom EA app traffic

Current boundary of proof:

- the new Python modules compile cleanly
- the GUI/runtime integration is in place
- but live proof against a real iPhone notification flow is still pending

Practical next step for another agent:

1. Run the updated BLE runtime on the second device.
2. Watch whether iOS exposes `ANCS` and whether it presents a notification-share
   authorization prompt on the current bonded path.
3. Generate real notifications and verify:
   - ANCS discovery succeeds
   - attribute responses arrive in the expected shape
   - the overlay renders and then returns to the now-playing screen
4. If the attribute stream fragments across multiple BLE notifications in a way
   the current parser does not yet tolerate, harden the parser before broadening
   scope further.

## 2026-05-20: live ANCS notification mirror proof succeeded on the second device

The first real end-to-end ANCS validation has now succeeded on live hardware.

Test setup:

- the runtime was launched from a temporary overlay in `/run/ancs-test`
- `/usr/lib/carthing` on the device was not overwritten for this validation pass
- the same existing BLE/HID runtime architecture was reused:
  - Bumble on `hci-socket:0`
  - the current `AMS` path
  - the new `ANCS` path in the same session

One important startup issue appeared first:

- the initial launch failed with:

```text
OSError: [Errno 16] Device or resource busy
```

- this happened while opening `hci-socket:0` on Bumble's `HCI_CHANNEL_USER`
- the working recovery was to reset the Bluetooth attach layer cleanly:
  - kill the current `carthing-btattach-mini` PID
  - rerun `/etc/init.d/S20-bt-init`
  - then start the ANCS runtime again

After that reset, the real runtime sequence succeeded:

- `hci-socket:0` opened
- display/UI initialized
- the iPhone connected
- encryption completed
- `AMS` came up successfully
- `ANCS` service discovery succeeded
- subscription to `Notification Source` and `Data Source` succeeded

The iPhone-side UX also behaved as required:

- iOS presented the notification-sharing permission prompt for `CarThing`
- the user explicitly allowed it

Real mirrored notification proof:

```text
2015-01-01 03:57:05,070 INFO ANCS source: event=0 category=5 count=1 uid=4 flags=0x10
2015-01-01 03:57:05,071 INFO ANCS request attributes for uid=4
2015-01-01 03:57:05,101 INFO ANCS notification ready: app=Reminders title='Любое напоминание' message='Сегодня, 21:11'
2015-01-01 03:57:05,101 INFO ANCS display: app=Reminders title='Любое напоминание' message='Сегодня, 21:11'
```

User-visible result:

- the notification appeared on the Car Thing screen
- the content was recognizable and useful
- the overlay later cleared automatically
- the UI returned to the normal now-playing state

Meaning:

1. Autonomous iPhone notification mirroring is no longer speculative here.
2. The no-companion-app rule remains intact.
3. `ANCS over BLE` is now a proven working system-events path on this project.
4. The next work should focus on hardening and productizing the layer, not on
   re-arguing whether notifications must come from generic iAP2 traffic.

## 2026-05-20: follow-up ANCS validation also proved removal, queueing, and long payload handling

The first success case was then followed by a tighter live matrix on the same
running session.

Additional observed behavior:

- real `ANCS removed` events were received, not just add/display traffic
- multiple notifications arrived back-to-back and were parsed cleanly
- a long Gmail notification payload was fetched and rendered without breaking the
  runtime or the now-playing path

Live examples:

```text
2015-01-01 04:09:15,347 INFO ANCS source: event=0 category=5 count=1 uid=5 flags=0x10
2015-01-01 04:09:15,453 INFO ANCS notification ready: app=Reminders title='Напоминание' message='Сегодня, 21:22'

2015-01-01 04:09:31,533 INFO ANCS source: event=0 category=5 count=2 uid=6 flags=0x10
2015-01-01 04:09:31,564 INFO ANCS notification ready: app=Reminders title='Напоминание' message='Сегодня, 21:23'

2015-01-01 04:10:09,572 INFO ANCS source: event=0 category=0 count=5 uid=7 flags=0x10
2015-01-01 04:10:09,634 INFO ANCS notification ready: app=Gmail title='donotreply@apple.com' message='Hi AK, We require additional files ...'
```

The most important narrow proof from this cycle was active removal while the
notification overlay was still live:

```text
2015-01-01 04:13:45,693 INFO ANCS source: event=0 category=5 count=1 uid=8 flags=0x10
2015-01-01 04:13:45,724 INFO ANCS notification ready: app=Reminders title='Тест на удаление' message='Сегодня, 21:27'
2015-01-01 04:13:45,724 INFO ANCS display: app=Reminders title='Тест на удаление' message='Сегодня, 21:27'
2015-01-01 04:13:51,873 INFO ANCS source: event=2 category=5 count=0 uid=8 flags=0x10
2015-01-01 04:13:51,873 INFO ANCS remove active notification uid=8
```

Meaning:

1. The runtime is not only able to show a notification once.
2. The ANCS path now has live proof for:
   - add
   - attribute fetch
   - display
   - queueing across multiple notifications
   - removal of an active on-screen notification
3. This substantially lowers the risk for promoting the ANCS layer from
   prototype/runtime overlay into the main productized path.

## 2026-05-20: genuine Live Activities are a separate app-based frontier, not an ANCS upgrade

After the ANCS notification path was proven live, the next architectural
question was whether modern iPhone `Live Activities` could be reached on the same
autonomous path.

Current Apple documentation points to a different answer:

- Live Activity forwarding is documented under `AccessoryLiveActivities`
- the forwarding path is implemented in an accessory data provider extension
- that extension must advertise capabilities for:
  - `AccessoryNotifications.NotificationsForwarding`
  - `AccessoryLiveActivities.LiveActivityForwarding`
- the documented flow explicitly assumes the iPhone-side extension model already
  created for forwarded notifications
- authorization is checked through framework APIs, and the system may present a
  unified permission UI for notification and Live Activity forwarding

Representative Apple documentation excerpts:

- `Receiving Live Activity updates and alerts on an accessory`
  - "you use an extension model that handles secure communication between iPhone and your accessory"
  - "Before adding support for Live Activity forwarding, you need to adopt iOS system notification forwarding and implement the extensions that handle communication between iPhone and your accessory."
- `AccessorySetupKit`
  - iOS/iPadOS framework for app-driven accessory discovery and configuration

Meaning for this project:

1. True Live Activities are **not** just a richer ANCS payload.
2. They are **not** currently reachable on the proven autonomous `ANCS + BLE`
   path.
3. Under the project's hard rule of **no companion app**, genuine Live
   Activities should now be treated as intentionally out of scope.
4. The correct language for future agents is no longer "maybe Live Activities are
   still hidden somewhere in ANCS"; it is:
   - classic notifications are proven through ANCS
   - first-class Live Activities belong to a separate Apple framework stack that
     conflicts with the current no-app architecture

## 2026-05-20: direct timer/Live Activity probe on the autonomous path produced no positive signal

After clarifying the documentation boundary, a direct empirical check was still
run so the conclusion would not depend only on reading Apple docs.

Test shape:

- restart the current ANCS runtime with file logging on the second device
- keep the same autonomous no-companion-app BLE/ANCS path
- launch a timer on the iPhone as a real Live Activity candidate
- inspect the remote runtime log for:
  - new app-specific ANCS events
  - repeated `event=1 modified` traffic
  - a new service or accessory-side path beyond the already-known ANCS/AMS setup

Observed log result:

- no new timer-specific or `WakeMinder`-specific ANCS payload appeared
- no obvious Live Activity update stream appeared
- only ordinary backlog notifications were seen:
  - `Feedbackassistant`
  - `Gmail`
  - `Bridge`

Practical meaning:

1. This is a strong negative result against the idea that true Live Activities
   simply "fall through" the already-proven autonomous ANCS path.
2. It does not prove that Apple never exposes Live Activities to accessories.
3. It does support the narrower and project-relevant conclusion that the current
   no-app CarThing runtime does not receive them as first-class objects in the
   same way it receives ordinary notifications.

## 2026-05-20: BLE-adjacent alert profile probe narrowed the timer/alarm frontier further

Because the timer/alarm still did not appear through ANCS, the next check was to
probe neighboring BLE service paths rather than assume ANCS was the whole story.

Fresh BLE service dump result against the real iPhone:

- `1800` Generic Access
- `1801` Generic Attribute
- `180A` Device Information
- `180F` Battery
- `1805` Current Time
- `7905F431-B5CE-4E99-A40F-4B1E122D00D0` ANCS
- `89D3502B-0F36-433A-8EF4-C502AD55F8DC` AMS
- `D0611E78-BBB4-4591-A5F8-487910AE4366` (custom)
- `9FA480E0-4967-4542-9390-D343DC5D04AE` (custom)

Important negative result:

- the iPhone did **not** expose either of the obvious standard BLE alert
  candidates:
  - `180E` Phone Alert Status
  - `1811` Alert Notification

Follow-up notify probe result:

- subscribed successfully to:
  - `AF0BADB1-5B99-43CD-917A-A77BC549E3CC`
  - `2A2B` Current Time
- read/subscribe to the other custom characteristic showed a stronger gate:
  - `8667556C-9A37-4C91-84ED-54EE27D90049`
  - read: `ATT_READ_NOT_PERMITTED_ERROR`
  - subscribe: `ATT_INSUFFICIENT_AUTHENTICATION_ERROR`

Live timer/alarm observation on the armed probe window:

- no useful notify traffic arrived on the subscribed custom characteristic
- no useful notify traffic arrived on `Current Time`
- no BLE-side signal emerged that could explain the missing timer/alarm on the
  accessory

Meaning:

1. The timer/alarm signal is not simply hiding in a standard neighboring BLE
   alert profile on this iPhone.
2. The remaining BLE-adjacent candidates are now narrow and specific, not broad:
   one auth-gated custom Apple service and one currently silent subscribable
   custom service.
3. The next rational frontier is to probe classic Bluetooth profile / SDP space
   instead of continuing to guess at generic BLE alert services.

## 2026-05-20: external Apple evidence now supports the negative Clock timer/alarm result

After the BLE-adjacent probe, an external source pass was added so the current
negative timer/alarm result would not rely only on our own device logs.

Relevant Apple-side evidence:

- The archived ANCS specification still describes a generic path for iOS
  notifications:
  - add / modify / remove events on `Notification Source`
  - optional attribute fetches on `Data Source`
  - category-based classification
- But the same specification also states that:
  - ANCS is not guaranteed to always be present
  - it is not a complete synchronization service
  - it only reflects iOS notifications that the system actually exposes in the
    current session

- A fresh Apple Developer Forums thread (`787123`) is especially relevant to our
  exact frontier:
  - the developer reports that ANCS delivery of system Clock alarm notifications
    worked through iPhone 13, but stopped on iPhone 14+ while still on iOS 18.x
  - the reported app identity is `com.apple.mobiletimer`
  - Apple DTS does not point to a documented replacement path; instead it asks
    for a bug report, Bluetooth logs, and a double-check that the notification
    is not arriving under a different category

- Apple’s current modern forwarding stack points somewhere else entirely:
  - `Accessory Notifications` is a new framework for forwarded iOS
    notifications on accessories
  - `Accessory Live Activities` layers Live Activity forwarding on top of that
  - both depend on an iPhone-side extension model and companion-app style
    transport/security plumbing
  - `Accessory Notifications` is currently documented as iPhone-only, companion
    app driven, introduced in iOS 26.5, and limited for customer use to EU
    devices/accounts at this stage

- Apple’s `ActivityKit` documentation still describes Live Activities as an
  app-owned surface shown on:
  - Lock Screen
  - Dynamic Island
  - CarPlay
  - a paired Mac or Apple Watch
  It does not describe a generic no-app accessory path for the built-in Clock
  app.

Practical meaning for this project:

1. Our negative autonomous result for system timer/alarm is now externally
   plausible, not just locally suspicious.
2. The missing Clock signal on the current CarThing path may be an Apple
   platform behavior change on newer iPhones, not merely a bug in our BLE code.
3. For a strict no-companion-app architecture, standard Clock timer/alarm
   mirroring should no longer be treated as a dependable Apple-supported target.
4. Apple Watch almost certainly reaches those alerts through a different Apple
   stack than the public autonomous ANCS path available to this project.
5. No Apple-documented accessory forwarding path was found for Stopwatch state
   as a first-class mirrored object.

## 2026-05-20: classic SDP probe proved the iPhone exposes HFP, PBAP, MAP, AVRCP, and A2DP services

After narrowing the BLE side, the next live step was a classic Bluetooth SDP
probe against the trusted iPhone address (`10:A2:D3:83:82:50`).

Important setup facts from the same session:

- classic inquiry does not currently reveal the iPhone as discoverable, which is
  expected and not a blocker once the address is already known
- `Remote Name Request` to `10:A2:D3:83:82:50` still returns `iPhone`
- the target toolchain had to be re-staged temporarily in `/run` as
  `/run/carthing-iap2-mini-probe`
- outbound SDP probing worked most reliably through direct Bumble access to the
  controller over `serial:/dev/ttyS1,3000000` after temporarily stopping the
  attach helper, then restoring `S20-bt-init`

Live SDP service-search result:

- `HFP_AG` `0x111F` -> handle `0x4f49111f`
- `HFP_HF` `0x111E` -> handle `0x4f49111f`
- `HEADSET_AG` `0x1112` -> not found
- `HEADSET` `0x1108` -> not found
- `PBAP_PSE` `0x112F` -> handle `0x4f49112f`
- `PBAP` `0x1130` -> handle `0x4f49112f`
- `MAP_MAS` `0x1132` -> handle `0x4f491132`
- `MAP_MNS` `0x1133` -> not found
- `MAP` `0x1134` -> handle `0x4f491132`
- `AVRCP_TARGET` `0x110C` -> handle `0x4f49110c`
- `AVRCP` `0x110E` -> handles `0x4f49110e`, `0x4f49110c`
- `AVRCP_CONTROLLER` `0x110F` -> handle `0x4f49110e`
- `A2DP` `0x110D` -> handle `0x4f49110a`
- `AUDIO_SOURCE` `0x110A` -> handle `0x4f49110a`
- `AUDIO_SINK` `0x110B` -> not found

Meaning:

1. The current iPhone pairing mode does expose a rich classic accessory surface;
   this is no longer speculative.
2. The strongest no-app classic candidates are now confirmed by live SDP, not
   just by protocol folklore:
   - HFP for calls / ring / call-state
   - PBAP for contacts / caller identity / recents
   - MAP for message access behavior
3. The iPhone presents itself as the expected media side too:
   - AVRCP target + controller
   - A2DP / audio source
4. The absence of Headset profile records makes plain HSP a lower-value branch
   than HFP.
5. The absence of `MAP_MNS` while `MAP_MAS` is present suggests that the next MAP
   work should start from message-access semantics rather than expecting a
   separate notification server role.

Practical next order after this proof:

1. HFP session bring-up and indicator/event logging.
2. PBAP attribute/channel discovery and then a minimal browse attempt.
3. MAP session bring-up after PBAP.
4. AVRCP/A2DP only as auxiliary signal paths, not as the main alert frontier.

## 2026-05-20: reusable classic profile probe added to the repo

To stop relying on ad-hoc shell heredocs for every classic test, a new reusable
probe script now exists in the repo:

- `overlay/usr/lib/carthing/classic_profile_probe.py`

What it does:

- `sdp-sweep`
  - opens a classic controller transport
  - connects to a trusted BR/EDR peer
  - queries the main profile records we care about for the current frontier:
    - HFP
    - PBAP
    - MAP
    - AVRCP
    - A2DP
  - prints SDP attributes plus any RFCOMM channel parsed from the
    `ProtocolDescriptorList`

- `hfp`
  - looks up the HFP Audio Gateway service through SDP
  - opens RFCOMM to the advertised channel
  - runs the bundled Bumble `HfpProtocol.initialize_service()` handshake
  - optionally sends extra AT commands and logs returned lines

Why this matters:

1. It turns the classic frontier into a first-class repo artifact, not a memory
   of one successful shell probe.
2. It gives future agents one place to extend toward PBAP/MAP after HFP.
3. It preserves the exact current test strategy in code on the test branch.

Current limitation observed during live validation:

- the new script passes local syntax validation
- on-device execution currently reaches:
  - transport open
  - then stalls/fails during Bumble `device.power_on()` when attempting to take
    over the controller in the current attached-controller state
- this means the immediate blocker for reusing the probe live is now the
  controller handoff path (`serial` vs `hci-socket`, plus attach ownership),
  not the SDP/HFP probe logic itself

Practical implication:

- the classic test branch now has a reusable HFP/SDP probe artifact
- the next narrow work item is to make Bumble attach cleanly to the already-live
  controller state on the target, or to fold the same logic into the existing C
  toolchain that already manages HCI ownership successfully

## 2026-05-20: controller ownership states are now much better characterized

Follow-up live tests narrowed the controller handoff problem more precisely than
the earlier generic "device.power_on() times out" summary.

Important stale-state discovery:

- `/run/carthing-btattach.pid` can point to an exited helper while
  `/sys/class/bluetooth/hci0` still exists
- in that state:
  - no live `carthing-btattach-mini` process is visible in `ps`
  - `S20-bt-init` tries to reattach and the helper log shows:
    - `line discipline: 15 -> 15`
    - `HCIUARTSETFLAGS: Device or resource busy`
- this means the current blocker is not just "helper still running"; it can also
  be a stale `N_HCI` ownership state on `/dev/ttyS1`

Direct detach proof:

- a manual Python ioctl sequence on the target:
  - `TIOCGETD`
  - `TIOCSETD -> 0`
  successfully changed the line discipline back to the normal TTY one
- after that:
  - the old line discipline was confirmed as `15` (`N_HCI`)
  - `/sys/class/bluetooth/hci0` disappeared immediately

New probe capability added:

- `classic_profile_probe.py` now also has a `--skip-power-on` mode
- this is meant for experiments on an already-configured `hci0`, where a full
  Bumble `device.power_on()` reset is undesirable or impossible

Live ownership-matrix results:

1. **Raw UART after manual `TIOCSETD -> 0`**
   - `hci0` disappears, so the UART is genuinely detached from the kernel stack
   - but Bumble still cannot complete `device.power_on()` over serial in the
     current controller state
   - tried transport specs:
     - `serial:/dev/ttyS1,3000000`
     - `serial:/dev/ttyS1,3000000,rtscts`
     - `serial:/dev/ttyS1,115200`
     - `serial:/dev/ttyS1,115200,rtscts`
   - all timed out at `device.power_on()`

2. **Fresh manual `carthing-btattach-mini` still alive**
   - a direct manual helper launch can recreate `/sys/class/bluetooth/hci0`
   - but in that fresh state Bumble `open_transport_or_link('hci-socket:0')`
     fails with:
     - `OSError: [Errno 16] Device or resource busy`

3. **Already-present `hci0` with `--skip-power-on`**
   - `classic_profile_probe.py --transport hci-socket:0 --skip-power-on ...`
     can open the transport in some states
   - but then `HCI_Create_Connection` itself times out during classic connect
   - this means "skip reset and just connect" is not yet enough by itself

What this means now:

1. The controller handoff bug is no longer vague.
2. There are at least three distinct ownership states that matter:
   - stale `hci0` with no live helper
   - fresh `hci0` with a live helper
   - raw detached UART with no `hci0`
3. None of the three states yet gives a clean reusable path for Bumble-based
   classic probing.
4. The most promising next direction is no longer random transport retry:
   - either reproduce the exact good state that made the one-off serial SDP sweep
     succeed earlier
   - or move the classic profile probing lower, into the existing C toolchain
     that already manages HCI ownership more reliably than Bumble on this target

## 2026-05-21: raw HCI socket over kernel-owned hci0 is now a proven fourth state

The next live pass changed the controller picture again in an important way.

What was tested:

- `classic_profile_probe.py` was tried on `hci-socket:0` without detaching the
  UART from the kernel
- that path still hit `OSError: [Errno 16] Device or resource busy`, so Bumble
  on `HCI_CHANNEL_USER` remains sensitive to current controller ownership
- a separate lower-level check was then run through the existing
  `/run/carthing-iap2-mini-probe` helper, but still against the live `hci0`
  device rather than detached raw UART

Important distinction:

- immediately after a plain fresh attach, `hci0` can exist while raw HCI
  commands still fail with:
  - `write(HCI cmd): Network is down`
  - `HCI Read Scan Enable: Invalid argument`
- this confirms again that mere existence of `/sys/class/bluetooth/hci0` is not
  the same as an operational classic-ready controller state

The decisive recovery step:

- running `carthing-iap2-mini-probe transport-daemon` on that fresh `hci0`
  brought the controller into the fully operational state
- after that, the same helper successfully completed:
  - `hci-read-scan` -> `0x03`
  - `hci-remote-name 10:A2:D3:83:82:50` -> `iPhone`
  - `hci-create-acl 10:A2:D3:83:82:50` -> ACL up, handle `0x000c`
- the paired kernel log also completed the expected BCM init sequence:
  - `BCM20703A2 (001.002.011) build 0000`
  - then `BCM (001.002.011) build 0353`

Meaning:

1. The current blocker is no longer best described as "classic is broken on this
   hardware" or even "kernel attach is broken".
2. The target now has a proven **fourth** meaningful controller state:
   - kernel-owned `hci0`
   - fully brought up via `transport-daemon`
   - accessible through raw HCI socket helpers
   - working for classic primitives without `TIOCSETD -> 0`
3. This is materially different from the failing detached-UART path:
   - raw UART + Bumble still times out on `HCI_Create_Connection`
   - raw HCI socket on live `hci0` succeeds once `HCIDEVUP` / classic init has
     been completed
4. The most promising next path is now clearer:
   - do **not** center the next implementation on raw UART takeover
   - instead, reuse the existing C-level HCI socket helpers on top of the
     kernel-owned controller, and only then bridge upward toward SDP / RFCOMM /
     HFP probing
5. Bumble is still useful at the service-logic layer, but the evidence now says
   the reliable controller boundary on this target is lower:
   - kernel attach + operational `hci0`
   - raw HCI socket / existing C helper path

## 2026-05-21: isolating post-identification traffic proved `ctl=0x40 sid=0`
## packets are bare link ACKs, not hidden service data

To stop guessing which post-identification service was producing the observed
`ignoring non-control link packet ctl=0x40 sid=0` lines, the probe was extended
with one new diagnostic mode:

- `CARTHING_IAP2_POST_ID_MODE=hid-only`

That allowed three clean live passes against the already trusted iPhone address
`10:A2:D3:83:82:50` while keeping the rest of the classic/iAP2 path unchanged:

- cached BR/EDR link key reuse
- live MFi auth through `CARTHING_MFI_HELPER=/run/carthing-mfi-probe`
- normal `AA00 -> AA02 -> AA05 -> 1D00 -> 1D02` flow

### Pass 1: `nowplaying-only`

Observed post-identification behavior:

- only one post-`1D02` control message was sent:
  - `[iap2-mini] -> link 0x40c8 seq=4 sid=1 len=42`
- the "non-control" packet still appeared:
  - `[iap2-mini] ignoring non-control link packet ctl=0x40 seq=74 sid=0 len=0`

Important context from the same log:

- the same `ctl=0x40 sid=0 len=0` packets already appeared earlier at:
  - seq `70` after `AA00`
  - seq `71` after `AA02`
  - seq `73` after `1D00`

### Pass 2: `hid-only`

Observed post-identification behavior:

- only one post-`1D02` control message was sent:
  - `[iap2-mini] -> link 0x6800 seq=4 sid=1 len=39`
- the same "non-control" packet still appeared:
  - `[iap2-mini] ignoring non-control link packet ctl=0x40 seq=77 sid=0 len=0`

Again, matching zero-length `ctl=0x40 sid=0` packets had already appeared before
`1D02`, including after:

- `AA00`
- `AA02`
- `1D00`

### Pass 3: `none`

This was the decisive control case:

- no post-identification service start message was sent at all
- the session still reached:
  - `[iap2-mini] <- link 1D02 IdentificationAccepted`
- then the iPhone resent the same control packet:
  - `[iap2-mini] <- link ctrl seq=91 sid=1 msg=0x1d02 len=6`
  - `[iap2-mini] duplicate link ctrl seq=91 msg=0x1d02`
  - `[iap2-mini] retransmit cached link 0x1d00 seq=3 sid=1 len=169`
- and a matching sid `0` ACK-only packet still followed:
  - `[iap2-mini] ignoring non-control link packet ctl=0x40 seq=91 sid=0 len=0`

### Meaning

This sharply narrows the interpretation of those packets:

1. `ctl=0x40` is pure ACK at the link layer.
2. `sid=0` here is not carrying hidden `HID`, `NowPlaying`, or `EA` payload.
3. `len=0` confirms there is no data payload in the packet at all.
4. The packet appears as a transport-level acknowledgement pattern across the
   whole session, not as a post-identification service event.

So the earlier suspicion was wrong:

- `ignoring non-control link packet ctl=0x40 sid=0` is **not** evidence of
  hidden `NowPlaying` or `ExternalAccessory` data that the parser is dropping.

What remains genuinely open after this isolation pass:

- whether the iPhone will ever send real `0x4800 NowPlayingUpdate`
- whether any `EA00 StartExternalAccessoryProtocolSession` will appear on the
  autonomous no-app path
- why `1D02` is duplicated in the `none` case and whether that reflects a
  transport retry / acknowledgement nuance rather than any higher-level service
  negotiation

Practical next step:

- stop chasing sid `0` / `ctl=0x40` as a hidden service path
- focus instead on:
  - explicit `EA02` / app-launch experiments
  - waiting for real incoming control messages like `EA00` or `4800`
  - any new non-zero-payload traffic on a non-control sid

## 2026-05-21: `EA02` frontier moved backward into `1D01` message-set
## encoding

After the sid `0` ACK boundary was closed, the next live experiment targeted
`EA02 RequestAppLaunch`.

First, the local probe was corrected to match public references more closely:

- `EA02` now uses `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID` as the outgoing
  parameter instead of treating the field as a UTI
- `1D03 IdentificationRejected` logging was upgraded to print **all** rejected
  parameter IDs, not just the first one

### Pass 1: `EA02-only` identification

Environment:

- `CARTHING_IAP2_ID_MSGSET=ea02-only`
- `CARTHING_IAP2_POST_ID_MODE=app-launch`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID=com.spotify.client`
- `CARTHING_IAP2_APP_LAUNCH_METHOD=0`

Result:

- auth still succeeded through `AA05`
- the session reached `1D00 StartIdentification`
- but the iPhone rejected identification before `1D02`

Exact rejection:

- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=8 preview=00 04 00 06 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

So the blocker was not `EA02` runtime behavior yet; it was already the
advertised message-set TLVs inside `1D01`.

### Pass 2: `hid-nowplaying` identification without app-launch

Control experiment:

- `CARTHING_IAP2_ID_MSGSET=hid-nowplaying`
- `CARTHING_IAP2_POST_ID_MODE=none`

Result:

- the same rejection happened again

Exact rejection:

- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=12 preview=00 06 00 06 40 c8 00 06 00 07 48 00`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

This is important because it shows the problem is **not specific to EA02**.

### Pass 3: hybrid `hid + nowplaying + ea02`

Environment:

- `CARTHING_IAP2_ID_MSGSET=hybrid`
- `CARTHING_IAP2_POST_ID_MODE=app-launch`
- `CARTHING_IAP2_APP_LAUNCH_TRIGGER=none`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID=com.spotify.client`

Result:

- again, auth succeeded
- again, identification was rejected

Exact rejection:

- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=12 preview=00 06 00 06 40 c8 00 06 00 07 48 00`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

### Meaning at this stage

These three passes narrowed the blocker, but did **not** close it fully:

1. The iPhone definitely rejects several current non-empty message-set
   combinations before `1D02`, including:
   - `EA02-only`
   - `hid-nowplaying`
   - the hybrid `hid + nowplaying + ea02`
2. The rejections consistently name:
   - `0x0006`
   - `0x0007`
3. So the present blocker is not yet "does iPhone launch the app?" but rather:
   - what exact encoding/semantics Apple expects for `0x0006` / `0x0007`
   - which side of that pair is actually causing the rejection on this path

At this point the honest statement was:

- our current multi-ID `1D01` message-set encoding was being rejected by the
  iPhone
- `EA02` could not yet be tested fairly with those variants

## 2026-05-21: sent-only `EA02` in `0x0006` is accepted; Spotify launch is
## proven, but explicitly out of scope as a product direction

The next live isolation pass split the two message-set fields instead of keeping
both non-empty.

Environment:

- `CARTHING_IAP2_ID_MSGSET=ea02-sent-only`
- `CARTHING_IAP2_POST_ID_MODE=app-launch`
- `CARTHING_IAP2_APP_LAUNCH_TRIGGER=none`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID=com.spotify.client`
- `CARTHING_IAP2_APP_LAUNCH_METHOD=0`

This variant advertised:

- `0x0006 = { EA02 }`
- `0x0007 = empty`

### Device-side result

Unlike the earlier variants, this path was accepted:

- `AA00 -> AA02 -> AA05` succeeded
- `1D00` arrived
- `1D02 IdentificationAccepted` arrived
- the accessory then sent:
  - `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`

The same result held on a longer observation window:

- after a `65s` wait there was still no incoming `EA00`
- no `EA03`
- no follow-on non-zero-payload EA session traffic

### User-visible result

The user confirmed the corresponding iPhone-side behavior:

- iOS showed the Spotify permission prompt
- the user allowed it
- the Spotify app opened

So the authenticated app-launch surface is now **proven live**.

### Updated meaning

This supersedes the overly strong earlier conclusion that both fields must stay
empty:

1. `0x0006` is **not** universally forbidden on this path.
2. A sent-only declaration containing `EA02` can coexist with successful
   identification.
3. The current practical blocker is narrower:
   - `0x0007` non-empty is still suspect
   - some multi-ID / bidirectional combinations around `0x0006`/`0x0007` are
     still rejected
   - but `EA02` itself is no longer blocked at identification if advertised only
     in `MessagesSentByAccessory`

### Boundary for the actual project goal

The user also clarified two important product constraints:

- Spotify itself is **not** the target of this project
- Spotify will likely not let the path go meaningfully further without a
  subscription

So this finding should be interpreted correctly:

- it proves that authenticated `RequestAppLaunch` is real and user-visible
- it does **not** change the main no-companion-app strategy
- it does **not** make Spotify a desirable downstream path for the actual
  product goal

Practical consequence:

- keep `EA02 sent-only` as a proven diagnostic capability
- do not pivot the project toward Spotify-specific behavior
- keep the main research focus on autonomous no-app surfaces and on the exact
  `0x0006/0x0007` boundary that governs what can be advertised safely in `1D01`

## 2026-05-21: the accepted `EA02` shim is extremely narrow

To stop hardcoding one-off message-set variants, the probe was extended with two
generic environment overrides:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS`

They accept comma-separated 16-bit message IDs and directly populate:

- `0x0006 MessagesSentByAccessory`
- `0x0007 MessagesReceivedFromDevice`

This made it possible to run a clean acceptance matrix without patching the code
for every hypothesis.

### Matrix 1: separate sent vs recv sides

All passes used:

- `CARTHING_IAP2_POST_ID_MODE=none`
- trusted classic link key
- live MFi auth (`AA00 -> AA02 -> AA05`)
- normal `1D00 StartIdentification`

#### Case: `0x0006 = { EA02 }`, `0x0007 = empty`

Environment:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS='0xEA02'`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS=''`

Result:

- accepted
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

This matches the earlier Spotify app-launch proof.

#### Case: `0x0006 = { 40C8, 40C9 }`, `0x0007 = empty`

Environment:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS='0x40C8,0x40C9'`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS=''`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=8 preview=00 08 00 06 40 c8 40 c9`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { 6800 }`, `0x0007 = empty`

Environment:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS='0x6800'`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS=''`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=8 preview=00 04 00 06 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

#### Case: `0x0006 = empty`, `0x0007 = { 4800 }`

Environment:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS=''`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS='0x4800'`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=6 preview=00 06 00 07 48 00`
- `[iap2-mini] 1D03 rejected param id=0x0007`

This is the cleanest live proof so far that non-empty `0x0007` is toxic on the
current path.

#### Case: `0x0006 = empty`, `0x0007 = { EA00, EA01 }`

Environment:

- `CARTHING_IAP2_ID_MSGSET_SENT_IDS=''`
- `CARTHING_IAP2_ID_MSGSET_RECV_IDS='0xEA00,0xEA01'`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=8 preview=00 04 00 06 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

### Matrix 2: enrich the accepted `EA02` shim on the sent side

The next question was whether the accepted shim was flexible, or whether it only
worked as the single bare ID `EA02`.

#### Case: `0x0006 = { EA02, 40C8, 40C9 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=8 preview=00 08 00 06 40 c8 40 c9`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { EA02, 6800 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=8 preview=00 04 00 06 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

#### Case: `0x0006 = { EA02, 40C8, 6800 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=10 preview=00 06 00 06 40 c8 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

### Meaning

This gives the current boundary much sharper shape:

1. The currently accepted non-empty message-set is **not** "EA-like messages in
   general".
2. It is much narrower:
   - `0x0006 = { EA02 }`
   - `0x0007 = empty`
3. `0x0007` remains the strongest live rejection boundary.
4. `NowPlaying` declarations in `0x0006` are rejected even with `0x0007` empty.
5. `HID` declarations in `0x0006` are also rejected.
6. Adding `NowPlaying` or `HID` to the accepted `EA02` shim breaks acceptance
   again.

So the accepted app-launch path is now best understood as an extremely narrow
compatibility shim:

- useful for avoiding errors and keeping the protocol path open
- useful as a user-visible proof that authenticated app launch exists
- **not** a general license to advertise richer control-session surfaces

Practical consequence:

- keep the bare `EA02` shim available as a protocol-safe placeholder
- keep `0x0007` empty unless a future live proof shows otherwise
- do not assume `NowPlaying` or `HID` can be made acceptable just by moving them
  to the sent side

### Matrix 3: single sent-side IDs around the accepted shim

To determine whether `EA02` was just one member of a larger accepted family, or
whether it was uniquely tolerated, a single-ID sweep was run with:

- `0x0007 = empty`
- one sent-side message ID at a time in `0x0006`

#### Case: `0x0006 = { EA01 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=6 preview=00 06 00 06 ea 01`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { 40C8 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=6 preview=00 06 00 06 40 c8`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { 40C9 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=6 preview=00 06 00 06 40 c9`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { 6801 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=6 preview=00 06 00 06 68 01`
- `[iap2-mini] 1D03 rejected param id=0x0006`

#### Case: `0x0006 = { 6803 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=8 preview=00 04 00 06 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

### Matrix 4: can `EA03` join the accepted shim?

Because `EA03` is the accessory-side EA status message, it was the next most
important candidate to test alongside `EA02`.

#### Case: `0x0006 = { EA03 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 07`
- `[iap2-mini] 1D03 rejected param id=0x0007`

#### Case: `0x0006 = { EA02, EA03 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 07`
- `[iap2-mini] 1D03 rejected param id=0x0007`

#### Case: `0x0006 = { EA03, 40C8, 40C9 }`, `0x0007 = empty`

Result:

- rejected
- `[iap2-mini] 1D03 params len=12 preview=00 08 00 06 40 c8 40 c9 00 04 00 07`
- rejected parameter IDs:
  - `0x0006`
  - `0x0007`

#### Case: `0x0006 = { EA02, EA03 }`, `0x0007 = { EA00 }`

Result:

- rejected
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 07`
- `[iap2-mini] 1D03 rejected param id=0x0007`

### Updated meaning

The accepted shim now looks even narrower than before:

1. `EA02` is not merely the "best" tested non-empty ID so far.
2. It is the **only** tested single sent-side ID in the current `EA` /
   `NowPlaying` / `HID` family that survives identification.
3. `EA03` cannot currently be advertised safely, even next to the accepted
   `EA02`.
4. This means the safe placeholder is not just "some small EA family surface";
   it is specifically:
   - `0x0006 = { EA02 }`
   - `0x0007 = empty`

So for the current live iPhone path, `EA02` should be treated as an almost
unique compatibility token, not as the first step of an openly expandable EA
message-set.

## 2026-05-21: `0x000A` remains toxic, but `0x000B` is accepted and does not
## break the safe `EA02` shim

Because the accepted `EA02` shim may still become useful later as a bridge into
our own app-specific path, the next layer checked whether two higher-level
identification fields could coexist with it:

- `0x000A` SupportedExternalAccessoryProtocol
- `0x000B` app/team-match style field (current local name:
  `PREFERRED_BUNDLE_SEED`)

All passes used the currently safe message-set:

- `0x0006 = { EA02 }`
- `0x0007 = empty`

### Matrix 5: add `0x000A` and/or `0x000B` on top of the safe shim

#### Control: safe shim only

Environment:

- no `0x000A`
- no `0x000B`

Result:

- accepted
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

#### Case: safe shim + `0x000A`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 0a`
- `[iap2-mini] 1D03 rejected param id=0x000a`

This cleanly re-proves that `0x000A` itself remains toxic even on top of the now
accepted `EA02` shim.

#### Case: safe shim + `0x000B`

Environment:

- `CARTHING_IAP2_PREFERRED_BUNDLE_SEED='ABCDE12345'`

Result:

- accepted
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

#### Case: safe shim + `0x000A` + `0x000B`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_PREFERRED_BUNDLE_SEED='ABCDE12345'`

Result:

- rejected
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 0a`
- `[iap2-mini] 1D03 rejected param id=0x000a`

So `0x000B` does not rescue `0x000A`; the rejection still lands squarely on
`0x000A`.

### Matrix 6: does `0x000B` break the actual app-launch runtime?

Because the field above was accepted at identification time, the next check kept
all of this together:

- safe shim (`0x0006 = { EA02 }`, `0x0007 = empty`)
- `0x000B = 'ABCDE12345'`
- `POST_ID_MODE=app-launch`
- `bundle_id=com.spotify.client`

Observed result:

- identification still succeeded:
  - `[iap2-mini] <- link 1D02 IdentificationAccepted`
- app launch request still went out:
  - `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`

So `0x000B` is not just tolerated during `1D01`; it also does not break the
already proven `EA02` launch path.

### Matrix 7: basic format pressure on `0x000B`

To see whether `0x000B` is treated like a tightly validated team identifier or
more like a soft placeholder, a small format sweep was run while keeping the safe
shim:

#### `0x000B = 'A'`

- accepted

#### `0x000B = 'ABCDE12345'`

- accepted

#### `0x000B = 'ABCDEFGHIJKLMNOP'`

- accepted

#### `0x000B = '1234567890'`

- accepted

### Meaning

This gives a new, cleaner split:

1. `0x000A` is still a hard rejection boundary on the current path.
2. `0x000B` is accepted much more freely.
3. `0x000B` also coexists with the safe `EA02` app-launch shim.
4. At least from the current acceptance surface, `0x000B` does **not** yet look
   like a tightly enforced team-ID gate.

For future archaeology this matters:

- `0x000A` still looks like the real EA-session blocker
- `0x000B` looks more like a soft annotation / placeholder that may remain usable
  later if a custom app path becomes relevant

That does **not** change the current product direction:

- no companion app is still the main rule
- Spotify is still only a diagnostic proof

But it does create a useful future breadcrumb:

- if a custom app path ever becomes relevant, `0x000B` is no longer the scary
  field; `0x000A` is

## 2026-05-20: the earlier "Spotify opened" reading was too strong; the
## user-visible result is currently only proven as an app-resolution / App Store
## path

The first live interpretation of the accepted `EA02` shim was that
`bundle_id=com.spotify.client` had opened Spotify directly.

That should no longer be treated as a confirmed user-visible fact.

Later user clarification tightened the observation:

- the iPhone presented a flow that pushed toward the App Store
- the store then reported that the application was unavailable there
- so the exact target application should be treated as unresolved

This preserves the strongest honest claim while removing the overstated one:

1. `EA02` is still a real, live, user-visible trigger on this path.
2. But what is currently proven is only:
   - an app-resolution / store-facing transition happens
   - not that Spotify itself definitely launched end-to-end

So the safe wording for the current frontier is:

- `EA02` produces a real iPhone-side reaction
- that reaction is compatible with app lookup / launch resolution
- the exact bundle-to-UI mapping still needs dedicated confirmation

## 2026-05-20: `0x000A` is no longer a proven blocker once it is encoded with the
## newer structured subfields

After the earlier section above, the `0x000A` result was revisited with a newer
builder that can send richer substructure, including:

- `match_action`
- `protocol_id`
- optional `native_transport_component_identifier`

All passes below kept the current safe compatibility shim:

- `0x0006 = { EA02 }`
- `0x0007 = empty`
- `POST_ID_MODE=none`

In every case below, identification succeeded:

- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=222`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

### Matrix 8: structured `0x000A` variants

#### Case: baseline structured `0x000A`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=1`
- `CARTHING_IAP2_EA_PROTOCOL_ID=0`
- no native transport component id

Result:

- accepted

#### Case: baseline + `native_transport_component_identifier = 1`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=1`
- `CARTHING_IAP2_EA_PROTOCOL_ID=0`
- `CARTHING_IAP2_EA_NATIVE_TC_ID=1`

Result:

- accepted

#### Case: `match_action = 0`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=0`
- `CARTHING_IAP2_EA_PROTOCOL_ID=0`
- `CARTHING_IAP2_EA_NATIVE_TC_ID=1`

Result:

- accepted

#### Case: `match_action = 2`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=2`
- `CARTHING_IAP2_EA_PROTOCOL_ID=0`
- `CARTHING_IAP2_EA_NATIVE_TC_ID=1`

Result:

- accepted

#### Case: `protocol_id = 1`

Environment:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=1`
- `CARTHING_IAP2_EA_PROTOCOL_ID=1`
- `CARTHING_IAP2_EA_NATIVE_TC_ID=1`

Result:

- accepted

### Updated meaning

This overturns the earlier "0x000A is inherently toxic" interpretation.

The stronger current reading is:

1. `0x000A` itself is not the proven problem anymore.
2. The earlier rejection was likely caused by an incomplete or malformed
   encoding, not by the semantic presence of
   `SupportedExternalAccessoryProtocol`.
3. The frontier therefore moves upward:
   - from "can we get `0x000A` accepted at all?"
   - to "what real session, app-resolution, or EA behavior follows once a valid
     `0x000A` is present?"

So the honest current blocker is no longer "`0x000A` rejected"; it is the still
unresolved behavior above that successfully accepted identification layer.

## 2026-05-21: structured `0x000A` also re-opens part of the old `0x0007` wall

The earlier message-set matrices that made `0x0007` look globally toxic were run
before the newer structured `0x000A` encoding had been validated.

That distinction now matters.

Using:

- `CARTHING_IAP2_EA_PROTOCOL='com.exrector.carthing.test'`
- `CARTHING_IAP2_EA_MATCH_ACTION=1`
- `CARTHING_IAP2_EA_PROTOCOL_ID=1`
- `CARTHING_IAP2_EA_NATIVE_TC_ID=1`

the message-set boundary was revisited.

### Matrix 9: `0x0007` / full EA contract with valid structured `0x000A`

#### Case: control baseline

Environment:

- `0x0006 = { EA02 }`
- `0x0007 = empty`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=222`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

#### Case: minimal recv-side EA start only

Environment:

- `0x0006 = { EA02 }`
- `0x0007 = { EA00 }`

Result:

- rejected
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=224`
- `[iap2-mini] <- link 1D03 IdentificationRejected`
- `[iap2-mini] 1D03 params len=4 preview=00 04 00 07`
- `[iap2-mini] 1D03 rejected param id=0x0007`

#### Case: recv-side EA session pair

Environment:

- `0x0006 = { EA02 }`
- `0x0007 = { EA00, EA01 }`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=226`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

#### Case: full EA session contract

Environment:

- `0x0006 = { EA02, EA03 }`
- `0x0007 = { EA00, EA01 }`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=228`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`

### Updated meaning

This is a significant correction to the earlier map.

1. `0x0007` is not globally forbidden.
2. With a valid structured `0x000A`, the iPhone accepts a real EA-session-shaped
   receive-side declaration.
3. But the acceptance is semantic, not arbitrary:
   - `EA00` alone is still rejected
   - `EA00 + EA01` is accepted
4. Accessory-side `EA03` can also now be advertised safely when paired with that
   fuller EA contract.

So the frontier has moved again:

- not "can we advertise any EA session surface at all?"
- but "why does accepted EA-session declaration still not produce live `EA00`
  traffic?"

## 2026-05-21: repeated Spotify permission prompts are now proven, but still do
## not yield a live EA session

After the user granted a Spotify-related permission prompt, the launch path was
retested with:

- accepted structured `0x000A`
- accepted full EA contract:
  - `0x0006 = { EA02, EA03 }`
  - `0x0007 = { EA00, EA01 }`
- `POST_ID_MODE=app-launch`
- `CARTHING_IAP2_APP_LAUNCH_TRIGGER=none`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID='com.spotify.client'`

Two long-window observations matter here.

### Idle case: no post-identification `EA02`

Environment:

- same accepted full EA contract
- `POST_ID_MODE=none`

Result:

- identification succeeded
- no spontaneous `EA00` appeared within the observation window

### Launch case: explicit `EA02`

Observed accessory-side result:

- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`
- no `EA00`
- no `EA03`
- no other new control/session traffic in the observed window

Observed user-visible result:

- the user reported another Spotify permission prompt at `02:52`

### Meaning

This cleanly separates two facts that should not be merged:

1. The Spotify-facing permission flow is now repeatable user-visible behavior for
   `EA02`.
2. A real EA session is still **not** proven:
   - not idle after accepted identification
   - not even after explicit `EA02`

So the next layer is no longer basic acceptance. It is runtime causality:

- what exact iPhone-side condition turns accepted EA-session metadata into live
  `EA00`
- whether that requires a different bundle, launch method, foreground state, or
  user action beyond the permission prompt itself

## 2026-05-21: the Spotify-facing prompt is now identified more precisely as an
## App Store fallback for an unavailable app

The earlier user-visible description was only "Spotify permission prompt".

It has now been tightened to a much more specific and useful statement.

Observed user-visible flow:

1. iPhone says the accessory `Spotify Card Think` uses an app that is not
   installed on this device.
2. iPhone offers to download it from the App Store.
3. App Store then reports that the application is unavailable there.

This gives the current `EA02` path a clearer meaning:

- `bundle_id=com.spotify.client` is not currently acting like a clean handoff into
  a working installed-app path
- it is acting like a bundle/app-resolution trigger that falls through to App
  Store lookup
- that lookup resolves to something unavailable on the present App Store path

The user's hypothesis fits the data well:

- this may be an old, stale, or otherwise retired Spotify-side mapping related to
  older Car Thing-era app integration

That remains a hypothesis, but it is now the best one consistent with the
observed UI.

## 2026-05-21: candidate `SupportedExternalAccessoryProtocol.name` strings do not
## yet change the runtime outcome

Because the next obvious guess was "maybe the right EA protocol string is
missing", a small live sweep was run with the same accepted full EA contract and
the same app-launch target:

- `0x0006 = { EA02, EA03 }`
- `0x0007 = { EA00, EA01 }`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID='com.spotify.client'`
- `POST_ID_MODE=app-launch`

Only `CARTHING_IAP2_EA_PROTOCOL` changed.

### Matrix 10: protocol-name sweep

#### Case: `com.exrector.carthing.test`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=228`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`
- no `EA00`
- no `EA03`

#### Case: `com.spotify.client`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=220`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`
- no `EA00`
- no `EA03`

#### Case: `com.spotify.superbird`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=223`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`
- no `EA00`
- no `EA03`

#### Case: `com.spotify.carthing`

Result:

- accepted
- `[iap2-mini] -> link 0x1d00 seq=3 sid=1 len=222`
- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.spotify.client`
- no `EA00`
- no `EA03`

### Meaning

This does **not** prove that none of these strings matters anywhere.

But it does prove a narrower and very relevant fact:

1. The tested `SupportedExternalAccessoryProtocol.name` values do not, by
   themselves, unlock a live EA session.
2. They also do not suppress the current `EA02 -> App Store fallback` path.
3. The visible iPhone behavior is therefore currently much more tightly coupled
   to the launch target `bundle_id=com.spotify.client` than to these tested EA
   protocol names.

So the next most economical user-visible control is no longer "try another
protocol string first"; it is "compare bundle-resolution behavior against other
bundle IDs".

## 2026-05-21: fake bundle control proves the current prompt is specific to
## `com.spotify.client`

To separate "generic `EA02` reaction" from "bundle-specific iPhone resolution",
one direct control pass was run with everything else held constant:

- accepted full EA contract:
  - `0x0006 = { EA02, EA03 }`
  - `0x0007 = { EA00, EA01 }`
- accepted structured `0x000A`
- `POST_ID_MODE=app-launch`
- `CARTHING_IAP2_APP_LAUNCH_TRIGGER=none`
- `CARTHING_IAP2_EA_PROTOCOL='com.spotify.client'`
- fake launch target:
  - `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID='com.exrector.noapp'`

Observed accessory-side result:

- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=34 bundle_id=com.exrector.noapp`

Observed user-visible result:

- the user saw nothing at all on iPhone

### Meaning

This is a strong control because it keeps the transport, identification, and EA
session advertisement constant while changing only the requested bundle.

It establishes:

1. The current Spotify/App Store flow is **not** a generic consequence of
   sending `EA02`.
2. It is specific to the real bundle target `com.spotify.client`.
3. Therefore the most likely current model is:
   - iPhone is performing a real bundle/app resolution step for
     `com.spotify.client`
   - that resolution falls through to an unavailable App Store target
   - fake bundle IDs do not trigger the same user-visible path at all

That sharply upgrades confidence in the stale/retired-mapping hypothesis around
the Spotify-specific path.

## 2026-05-21: public App Store evidence weakens the "stale Spotify mapping"
## hypothesis

The earlier best-fit hypothesis for the Spotify/App Store fallback was:

- `com.spotify.client` might resolve through an old or retired Car Thing-era
  Spotify mapping

That is now too strong.

Public current-store evidence shows:

1. `com.spotify.client` is the current live iOS bundle identifier for the main
   Spotify app.
2. Apple's own lookup API returns a valid modern Spotify listing for live
   storefronts such as `us` and `gb`.
3. The same lookup returns no result for at least some storefronts, including
   `ru`.

So the user-visible flow:

- accessory says app not installed
- iPhone offers App Store download
- App Store says app unavailable

is now better explained as:

- real bundle resolution for a valid modern Spotify app
- followed by storefront/region unavailability on the current Apple ID store

rather than by a fundamentally dead bundle identifier.

This does **not** change the accessory-side findings:

- fake bundle IDs still produce nothing
- tested `SupportedExternalAccessoryProtocol.name` values still do not produce
  `EA00`
- real EA session establishment remains unproven

But it does improve the user-visible interpretation:

- the Spotify path is likely a current, real app-resolution path
- the App Store failure is probably downstream of store availability, not bundle
  validity

## 2026-05-21: `EA02` can also redirect into installed system apps on the same
## Spotify protocol path

The next question after the Spotify/App Store clarification was whether the
observed user-visible path was unique to Spotify, or whether the same accepted
iAP2 surface could push iPhone into other already installed apps.

The tests below kept the same working accessory-side shape:

- accepted full EA contract:
  - `0x0006 = { EA02, EA03 }`
  - `0x0007 = { EA00, EA01 }`
- accepted structured `0x000A`
- `CARTHING_IAP2_EA_PROTOCOL='com.spotify.client'`
- `POST_ID_MODE=app-launch`

Only `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID` changed.

### Matrix 11: installed system-app redirects

#### Case: `bundle_id=com.apple.Music`

Observed accessory-side result:

- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=31 bundle_id=com.apple.Music`

Observed user-visible result:

- iPhone showed a permission prompt titled `Music`
- the text said Music wanted permission to communicate with `Spotify Car Thing`
- after the user tapped `Allow`, iPhone opened the Music app

Immediate follow-up:

- a second pass after permission grant still did **not** produce `EA00`
- no new EA session traffic appeared in the accessory log

#### Case: `bundle_id=com.apple.Preferences`

Observed accessory-side result:

- `[iap2-mini] <- link 1D02 IdentificationAccepted`
- `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=37 bundle_id=com.apple.Preferences`

Observed user-visible result:

- iPhone showed a permission prompt titled `Settings`
- the text said Settings wanted permission to communicate with `Spotify Car Thing`
- after the user tapped `Allow`, iPhone opened Bluetooth settings showing paired
  devices

Immediate follow-up:

- a clean retry after permission grant again reached:
  - `[iap2-mini] <- link 1D02 IdentificationAccepted`
  - `[iap2-mini] -> link 0xEA02 seq=4 sid=1 len=37 bundle_id=com.apple.Preferences`
- but still showed no `EA00`
- and no `EA03`

### Meaning

This is a major widening of the map.

1. The current `EA02` path is not just "Spotify or App Store".
2. It can redirect into at least multiple installed system apps:
   - Music
   - Settings / Bluetooth
3. So the behavior is broader than a single hardcoded Spotify branch.
4. But the deeper separation still stands:
   - app redirection / foregrounding is real
   - EA session establishment is still not proven

So the frontier now looks like this:

- **proven:** bundle-specific user-visible app redirects on iPhone
- **still missing:** actual `EA00 StartExternalAccessoryProtocolSession`

That means "launch surface" and "EA transport surface" should now be treated as
distinct layers of the same system, not as one thing.

## 2026-05-21: app-launch grants become user-visible no-ops on repeat, and simple
## identity tweaks do not reset them

The next obvious question after proving system-app redirects was whether those
permission prompts are:

- permanently repeatable
- or a first-grant transition that later becomes quiet

### Matrix 12: repeat-after-allow behavior

#### Case: `com.apple.Music` after prior `Allow`

Observed accessory-side result:

- normal path still completed:
  - `1D02 IdentificationAccepted`
  - `EA02 bundle_id=com.apple.Music`

Observed user-visible result:

- nothing

#### Case: `com.apple.Preferences` after prior `Allow`

Observed accessory-side result:

- normal path still completed:
  - `1D02 IdentificationAccepted`
  - `EA02 bundle_id=com.apple.Preferences`

Observed user-visible result:

- nothing

So the current behavior is not "prompt forever". For the tested system apps it
looks like:

- first run -> permission prompt + redirect
- later runs -> user-visible no-op

### Matrix 13: can cosmetic accessory identity changes reset that state?

To see whether iPhone keys this grant to the prompt-visible accessory identity,
the accessory strings were overridden as:

- `0x0000 = 'Probe Alt Thing'`
- `0x0001 = 'Probe Mk2'`
- `0x0002 = 'Exrector Labs'`

while keeping the same Settings launch path.

Observed accessory-side result:

- normal path still completed:
  - `1D02 IdentificationAccepted`
  - `EA02 bundle_id=com.apple.Preferences`

Observed user-visible result:

- nothing

So changing the strings that are most likely to appear in the permission prompt
is **not** enough to bring the prompt back.

### Matrix 14: can serial-number override reset that state?

Because serial number is a stronger candidate for accessory identity than the
display strings, the probe was extended with:

- `CARTHING_IAP2_SERIAL`

and retested with:

- `CARTHING_IAP2_SERIAL='PROBE-SERIAL-0002'`
- same Settings launch path

Observed accessory-side result:

- normal path still completed:
  - `1D02 IdentificationAccepted`
  - `EA02 bundle_id=com.apple.Preferences`

Observed user-visible result:

- nothing

### Meaning

This tightens the cache boundary significantly.

1. The first-grant prompt/redirect does not repeat indefinitely.
2. Repeating the same path after `Allow` becomes a user-visible no-op.
3. That no-op state is **not** reset by:
   - prompt-visible name change
   - model change
   - manufacturer change
   - the tested serial override

So the next meaningful hypothesis is no longer "maybe tweak one more cosmetic
field". It is:

- either the iPhone decision is keyed to deeper identity/state
- or it is keyed to pair/bond/remembered-accessory state outside the tested
  `IdentificationInformation` fields

That elevates the user's earlier intuition:

- the next truly informative test is likely an explicit forget/unpair reset,
  rather than another small TLV rename

## 2026-05-21: file-backed `AA01` still preserves first-time app-permission
## behavior on a fresh bundle

To probe whether the decisive anchor might sit in the exported MFi credential
identity rather than in the *live* act of reading the certificate from the chip
at `AA00`, a small runtime helper wrapper was introduced:

- `aa01-live` was redirected to `aa01-file <saved pkcs7.bin>`
- `aa03` still used live chip signing

So this was **not** a no-chip experiment. It was a narrower split:

- certificate blob source = file-backed replay
- challenge signing = still live from the physical MFi path

### Matrix 15: replay-helper on a fresh bundle

Environment:

- same accepted iAP2 surface as before
- `CARTHING_MFI_HELPER=/run/mfi-replay-helper.sh`
- `CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID='com.apple.MobileSMS'`

Observed accessory-side result:

- normal authenticated path still completed:
  - `AUTH COMPLETE status=0x00`
  - `AA00`
  - `AA02`
  - `AA05 auth success`
  - `1D02 IdentificationAccepted`
  - `EA02 bundle_id=com.apple.MobileSMS`

Observed user-visible result:

- iPhone showed a fresh permission prompt for `Messages`
- the user tapped `Allow`

Immediate repeat:

- the same replay-helper `Messages` path again completed through:
  - `AA05`
  - `1D02`
  - `EA02 bundle_id=com.apple.MobileSMS`
- but after the permission grant, the user reported no further visible effect

### Meaning

This is not yet proof that the MFi chip is the sole anchor.

But it is a strong narrowing:

1. The first-time app-permission behavior does **not** depend on live AA00 cert
   fetch in the narrow sense.
2. A previously captured PKCS#7 cert blob, paired with live challenge signing,
   is enough to preserve the same class of iPhone-side behavior on a fresh app.
3. So the important thing here looks more like the **stable MFi credential
   identity** presented to the phone than the literal provenance of the AA00
   bytes at runtime.

In other words:

- the experiment strengthens the user's MFi-anchor hypothesis
- but it still does not cleanly separate:
  - "identity comes from the MFi certificate/signing surface"
  - from
  - "identity comes from some even deeper remembered accessory state that
    remains aligned with that credential"

## 2026-05-21: C-level classic SDP parser fixed, and HFP service-level exchange is now proven

After parking the deeper `qt-superbird-app` archaeology for later, the live focus
shifted to product-facing classic profiles on the already trusted iPhone address
`10:A2:D3:83:82:50`.

The first blocker in that branch was controller ownership:

- Bumble on `hci-socket:0` either hit `OSError: [Errno 16] Device or resource busy`
  or, after a clean attach reset, timed out at `HCI_Create_Connection`
- the existing C helper path, however, could still make the controller
  classic-ready again under `transport-daemon`

That led to the next clean-room step inside `carthing_iap2_mini.c` itself:

- a new command:

```text
carthing-iap2-mini sdp-rfcomm <AA:BB:CC:DD:EE:FF> <service>
```

- this does:
  - outbound `HCI_Create_Connection`
  - authenticated `L2CAP` connect to `PSM 0x0001`
  - real `SDP ServiceSearchAttributeRequest`
  - RFCOMM channel extraction for a named classic service

Supported aliases now include:

- `hfp_ag`
- `hfp_hf`
- `pbap_pse`
- `pbap`
- `map_mas`
- `map`
- `avrcp_target`
- `avrcp`
- `avrcp_controller`
- `a2dp`
- `audio_source`

The first version reached real iPhone SDP responses but still returned
`channel=-1`; the parser was then fixed to handle the actual iPhone response
shape:

- outer sequence-of-attribute-lists
- inner attr-list parsing
- `ProtocolDescriptorList`
- `AdditionalProtocolDescriptorLists` fallback

Live result after the parser fix:

```text
[iap2-mini] SDP discovered RFCOMM channel=8  for service=hfp_ag   peer=10:A2:D3:83:82:50
[iap2-mini] SDP discovered RFCOMM channel=13 for service=pbap_pse peer=10:A2:D3:83:82:50
[iap2-mini] SDP discovered RFCOMM channel=2  for service=map_mas  peer=10:A2:D3:83:82:50
```

This is a major narrowing step:

1. the blocker is no longer controller ownership by itself
2. no longer outbound SDP reachability
3. and no longer RFCOMM channel discovery for the main product-facing services

The next clean-room step then became one level higher:

- a second new command:

```text
carthing-iap2-mini hfp-at <AA:BB:CC:DD:EE:FF> <AT...>
```

- this now:
  - discovers `hfp_ag`
  - connects RFCOMM to the discovered channel
  - sends one AT line with trailing `\r`
  - prints returned bytes to stdout

Live proof:

```text
[iap2-mini] SDP discovered RFCOMM channel=8 for service=hfp_ag peer=10:A2:D3:83:82:50
[iap2-mini] RFCOMM connect peer=10:A2:D3:83:82:50 ch=8
[iap2-mini] RFCOMM connected peer=10:A2:D3:83:82:50 ch=8 for service=hfp_ag

+BRSF:495

OK
```

Additional live HFP proof:

```text
+CIND: ("service",(0-1)),("call",(0-1)),("callsetup",(0-3)),("battchg",(0-5)),("signal",(0-5)),("roam",(0-1)),("callheld",(0-2))

OK
```

and:

```text
+CIND: 1,0,0,5,3,0,0

OK
```

Meaning:

1. `HFP` is no longer only "visible in SDP"
2. HFP RFCOMM connect is proven on the current no-app classic path
3. HFP AT/service-level exchange is also proven on that path
4. the strongest remaining classic product frontiers now look like:
   - unsolicited HFP indicator flow / `AT+CMER`
   - PBAP browse/setup on channel `13`
   - MAP session bring-up on channel `2`

The next small refinement then turned that first HFP exchange into a real
service-level connection helper:

- a third new command:

```text
carthing-iap2-mini hfp-slc <AA:BB:CC:DD:EE:FF>
```

- this runs on one RFCOMM session:
  - `AT+BRSF=2072`
  - `AT+CIND=?`
  - `AT+CIND?`
  - `AT+CMER=3,0,0,1`

Live result:

```text
[iap2-mini] HFP tx AT+BRSF=2072
+BRSF:495
OK
[iap2-mini] HFP tx AT+CIND=?
+CIND: ("service",(0-1)),("call",(0-1)),("callsetup",(0-3)),("battchg",(0-5)),("signal",(0-5)),("roam",(0-1)),("callheld",(0-2))
OK
[iap2-mini] HFP tx AT+CIND?
+CIND: 1,0,0,5,3,0,0
OK
[iap2-mini] HFP tx AT+CMER=3,0,0,1
OK
```

Meaning:

1. HFP is now proven at the **service-level connection** stage, not only as
   isolated AT probes
2. `AT+CMER` is accepted by the iPhone AG on the current no-app classic path
3. the next narrow live experiment is now straightforward:
   - keep the same RFCOMM session open
   - trigger a real incoming or outgoing call event
   - watch for unsolicited `+CIEV` indicator updates

One more capability-only pass was then used to keep moving without a real phone
call:

```text
AT+CHLD=?
AT+CLIP=1
AT+CCWA=1
```

Live result:

```text
+CHLD: (0,1,1x,2,2x,3)
OK
```

but:

```text
AT+CLIP=1  -> ERROR
AT+CCWA=1  -> ERROR
```

Meaning:

1. the iPhone AG exposes a real HFP call-control surface (`CHLD`)
2. direct caller-ID / call-waiting notification enable is not yet confirmed on
   this probe path
3. in the absence of a real call trigger, the strongest ready next step remains
   `+CIEV` observation during an actual state change

That missing trigger was then found in a simple product-realistic way:

- initiate an outgoing FaceTime call to the same iPhone account / self-contact

The same `hfp-slc` helper was rerun with a longer linger window, and this time
the live session emitted unsolicited HFP indicators:

```text
+CIEV: 3,2
+CIEV: 3,3
+VGS=4
+CIEV: 3,0
```

Interpreting that against the already proven `AT+CIND=?` schema:

- indicator `3` = `callsetup`

So the current observed outgoing-call sequence is:

1. `callsetup -> 2`
2. `callsetup -> 3`
3. `callsetup -> 0`

with one unsolicited speaker-gain update in the middle:

- `+VGS=4`

Meaning:

1. the iPhone is now proven to emit real unsolicited HFP state changes into the
   clean-room C helper stack
2. HFP on the no-app classic path is no longer only:
   - SDP-discoverable
   - RFCOMM-connectable
   - AT-queryable
   but also **stateful and eventful**
3. the next narrow HFP questions are now higher-level:
   - incoming-call / ringing transitions
   - `call` / `callheld` indicator behavior
   - whether call-control commands from the exposed `CHLD` surface have useful
     product meaning for the project

The next lateral step then moved from `HFP` into `PBAP`, still using the same
clean-room C helper path and the already proven RFCOMM channel discovery:

- a fourth new command:

```text
carthing-iap2-mini pbap-connect <AA:BB:CC:DD:EE:FF>
```

- this now:
  - discovers `pbap_pse`
  - connects RFCOMM to the discovered channel
  - sends one OBEX `CONNECT` request with the PBAP Target UUID
  - reads one OBEX response packet
  - extracts `Connection ID` if present

Live proof:

```text
[iap2-mini] SDP discovered RFCOMM channel=13 for service=pbap_pse peer=10:A2:D3:83:82:50
[iap2-mini] RFCOMM connect peer=10:A2:D3:83:82:50 ch=13
[iap2-mini] RFCOMM connected peer=10:A2:D3:83:82:50 ch=13 for service=pbap_pse
[iap2-mini] PBAP tx OBEX CONNECT peer=10:A2:D3:83:82:50 ch=13 len=26
[iap2-mini] PBAP rx opcode=0xa0 len=31 preview=a0 00 1f 10 00 0f a0 cb 50 e2 c0 e0 4a 00 13 79 61 35 f0 f0 c5 11 d8 09 66 08 00 20 0c 9a 66
[iap2-mini] PBAP connection-id=0x50e2c0e0
opcode=0xa0 version=0x10 flags=0x00 max_rx=4000 channel=13 connection_id=0x50e2c0e0
```

Important response details:

1. `opcode=0xa0` means the iPhone accepted the OBEX `CONNECT`
2. the negotiated OBEX receive size is `4000` bytes (`0x0fa0`)
3. the response includes `Connection ID = 0x50e2c0e0`, which must be echoed in
   later PBAP requests
4. the response also includes a `Who (0x4A)` header containing the same PBAP
   target UUID:
   - `79 61 35 f0 f0 c5 11 d8 09 66 08 00 20 0c 9a 66`

Meaning:

1. `PBAP` is no longer only visible in SDP and no longer only "channel known"
2. the iPhone now demonstrably accepts real PBAP OBEX session bring-up on the
   current no-app classic path
3. the strongest next PBAP step is no longer protocol entry itself, but one
   level higher:
   - `SetPath`
   - `PullPhoneBook`
   - or another minimal browse/list request using the echoed `Connection ID`

That next PBAP step is now also proven live.

- a fifth new command:

```text
carthing-iap2-mini pbap-pull <AA:BB:CC:DD:EE:FF> <name>
```

- this now:
  - performs the same PBAP `OBEX CONNECT`
  - reuses the echoed `Connection ID`
  - sends one `PullPhoneBook` GET with:
    - `Type = x-bt/phonebook`
    - `Name = telecom/pb.vcf`
    - app params:
      - `MaxListCount=1`
      - `ListStartOffset=0`
      - `Format=0`
  - handles `OBEX Continue` / final `Success`
  - concatenates returned `Body` / `EndOfBody`

Live proof:

```text
[iap2-mini] PBAP tx PullPhoneBook peer=10:A2:D3:83:82:50 ch=13 name=telecom/pb.vcf conn_id=0x50e2c0e0 max_list=1 offset=0 format=0 len=73
[iap2-mini] PBAP pull rx opcode=0x90 len=3 preview=90 00 03
[iap2-mini] PBAP pull rx opcode=0xa0 len=150 preview=a0 00 96 49 00 93 42 45 47 49 4e 3a 56 43 41 52 44 0d 0a 56 45 52 53 49 4f 4e 3a 32 2e 31 0d 0a 46 4e 3b 43 48 41 52 53 45 54 3d 55 54 46 2d
[iap2-mini] PBAP pull complete body_len=144
BEGIN:VCARD
VERSION:2.1
FN;CHARSET=UTF-8:Мой номер
N;CHARSET=UTF-8:;Мой номер
TEL;TYPE=CELL:+79523713710
UID:0
END:VCARD
```

Important protocol details:

1. the first response packet is a bare `OBEX Continue` with no headers at all:
   - `90 00 03`
2. the final response begins directly with `EndOfBody (0x49)` after the 3-byte
   OBEX header, which is different from the 7-byte `CONNECT` response shape
3. the returned vCard is `VERSION:2.1`
4. on this query shape, the iPhone did not include a `PhonebookSize`
   application-parameter header in the observed response

Meaning:

1. `PBAP` on the no-app classic path is now proven all the way up to **real
   contact-data retrieval**
2. this is no longer merely "session entry" or "RFCOMM reachability"
3. the next PBAP frontiers are now product-shaped rather than protocol-shaped:
   - caller-identity-oriented phonebooks / recents:
     - `telecom/ich.vcf`
     - `telecom/och.vcf`
     - `telecom/mch.vcf`
     - `telecom/cch.vcf`
   - larger `MaxListCount`
   - paged pulls via `ListStartOffset`

The next lateral step then moved into `MAP`, but this time the result was
important precisely because it failed *after* all the lower layers had already
been proven:

- a sixth new command:

```text
carthing-iap2-mini map-connect <AA:BB:CC:DD:EE:FF>
```

- this now:
  - discovers `map_mas`
  - connects RFCOMM to channel `2`
  - sends OBEX `CONNECT` with the MAP MAS Target UUID:
    - `bb582b40-420c-11db-b0de-0800200c9a66`

Live proof:

```text
[iap2-mini] SDP discovered RFCOMM channel=2 for service=map_mas peer=10:A2:D3:83:82:50
[iap2-mini] RFCOMM connect peer=10:A2:D3:83:82:50 ch=2
[iap2-mini] RFCOMM connected peer=10:A2:D3:83:82:50 ch=2 for service=map_mas
[iap2-mini] MAP tx OBEX CONNECT peer=10:A2:D3:83:82:50 ch=2 len=26
[iap2-mini] MAP rx opcode=0xc3 len=7 preview=c3 00 07 10 00 0f a0
[iap2-mini] MAP OBEX CONNECT did not succeed (opcode=0xc3)
```

Important interpretation:

1. this is **not** an SDP failure
2. **not** an RFCOMM failure
3. **not** a malformed-OBEX-shape failure
4. the iPhone returns a connect-shaped OBEX response body (`version=0x10`,
   `flags=0x00`, `max_rx=0x0fa0`) together with a non-success status `0xc3`

Meaning:

1. `MAP` is now proven to be advertised and reachable all the way up to the
   OBEX policy boundary
2. the current blocker is higher-level authorization / pairing policy on the
   iPhone side, not transport or basic protocol mechanics
3. the next narrow question is now user-state-specific rather than
   reverse-engineering-specific:
   - whether this Bluetooth pairing currently has the relevant
     notifications/message-access permission enabled

## 2026-05-21: repaired-pair BLE ANCS path again proves practical message visibility without classic MAP

The next successful pivot returned to the already working `CarThing` BLE
runtime on the repaired pair and treated `ANCS` as the safe "MAP under another
sauce" path.

This mattered because the previous impression had been misleading:

- the repository already contained `ANCS` support
- but the target device was missing `ancs_client.py`
- and the live target also had an older `now_playing_ui.py` that still lacked
  `render_notification`

So the first restart with the new runtime code did **not** fail because iPhone
withheld notifications. It failed because the live target was running a drifted
file set.

The repaired BLE pass therefore included these concrete fixes:

1. sync the missing `ancs_client.py` onto the target
2. serialize post-pair startup through one explicit path instead of racing
   separate `ANCS` / `AMS` task launches
3. sync the newer `now_playing_ui.py` so notification rendering stops crashing
4. free a small amount of rootfs space by deleting Python `__pycache__`
   directories when `/` hit `100%` and blocked further file sync

Live repaired-pair proof:

```text
2015-01-01 19:35:44,792 INFO Post-pair services start: handle=64 reason=link-encrypted encrypted=True
2015-01-01 19:35:44,793 INFO ANCS: using client id=0x7f7a5e9fd0 on 10:A2:D3:83:82:50/P
2015-01-01 19:35:45,740 INFO ANCS: subscribed data=0x0021 source=0x001E client=0x7f7a5e9fd0 handles=['0x001E', '0x0021']
2015-01-01 19:35:45,741 INFO ANCS готов — жду уведомления
2015-01-01 19:35:45,804 INFO ANCS source: event=0 category=4 count=1 uid=0 flags=0x15
2015-01-01 19:35:45,830 INFO ANCS source: event=0 category=0 count=1 uid=1 flags=0x15
2015-01-01 19:35:45,861 INFO ANCS notification ready: app=Messages title='Дмитрий Попандопуло' message='Офис сегодня'
2015-01-01 19:35:45,862 INFO ANCS display: app=Messages title='Дмитрий Попандопуло' message='Офис сегодня'
2015-01-01 19:35:45,965 INFO ANCS notification ready: app=Feedbackassistant title='Ассистент обратной связи' message='Apple отвечает на Ваш отзыв: During a phone call on eSIM1, the second line (eSIM2) is completely disconnected (loses network connection)'
2015-01-01 19:35:45,965 INFO ANCS display: app=Feedbackassistant title='Ассистент обратной связи' message='Apple отвечает на Ваш отзыв: During a phone call on eSIM1, the second line (eSIM2) is completely disconnected (loses network connection)'
```

Meaning:

1. the current repaired BLE pair again proves practical, autonomous
   notification mirroring
2. this now includes a real `Messages` payload with sender-like title and body
   text, not just reminders or generic app banners
3. the no-companion-app rule remains intact
4. for practical notification/message visibility, classic `MAP` is no longer
   the only plausible route on this project

An additional refinement then decoded the `ANCS` event flags into something more
product-useful.

Live example:

```text
2015-01-01 19:50:47,242 INFO ANCS source: event=0 category=0 count=1 uid=0 flags=0x15 (silent, preexisting, negative-action)
2015-01-01 19:50:47,332 INFO ANCS notification ready: app=Feedbackassistant title='Ассистент обратной связи' message='Apple отвечает на Ваш отзыв: During a phone call on eSIM1, the second line (eSIM2) is completely disconnected (loses network connection)' flags=silent,preexisting,negative-action
```

This sharpens the frontier again:

1. the BLE path exposes not only title/body-style notification payloads, but
   also action-related metadata
2. the observed `0x15` means:
   - `silent`
   - `preexisting`
   - `negative-action`
3. therefore the next meaningful `ANCS` question is no longer "does it work at
   all?" but "how far toward actionable message/notification UX can this path be
   pushed before classic `MAP` is truly needed?"

That next question was then answered one level deeper with a live
`Perform Notification Action` pass on the same repaired BLE runtime.

The runtime was extended in a deliberately narrow way:

- `ANCSClient` now has an explicit `perform_notification_action()` helper
- `back` is temporarily mapped to ANCS negative action **only while**
  a notification overlay is active **and only when** the iPhone-set ANCS flags
  include `negative-action`
- normal media-button behavior remains unchanged outside that narrow case

Live proof with `Reminders`:

```text
2015-01-01 20:02:42,731 INFO ANCS source: event=0 category=5 count=1 uid=1 flags=0x10 (negative-action)
2015-01-01 20:02:42,777 INFO ANCS notification ready: app=Reminders title='Тест' message='Сегодня, 13:16' flags=negative-action
2015-01-01 20:02:42,777 INFO ANCS display: app=Reminders title='Тест' message='Сегодня, 13:16' flags=negative-action
2015-01-01 20:02:48,628 INFO Back button → ANCS negative action uid=1 app=Reminders
2015-01-01 20:02:48,629 INFO ANCS perform action: uid=1 action=negative
2015-01-01 20:02:48,671 INFO ANCS source: event=2 category=5 count=0 uid=1 flags=0x10 (negative-action)
2015-01-01 20:02:48,672 INFO ANCS remove active notification uid=1
```

Meaning:

1. the current BLE `ANCS` path is no longer just "read notification text"
2. the iPhone-side negative action path is now proven live on this project
3. for at least one real notification category (`Reminders`), the accessory can:
   - receive the notification
   - inspect action capability via ANCS flags
   - invoke the negative action back onto iPhone
   - observe the removal event that follows
4. this materially strengthens the case that `ANCS` is the practical near-term
   substitute for a large slice of what the user wanted from `MAP`, even though
   it still does **not** prove inbox browsing, thread history, or message send

The next live step then proved the complementary **positive** action path on an
incoming phone call.

Live log:

```text
2015-01-01 20:31:08,390 INFO ANCS source: event=0 category=1 count=1 uid=3 flags=0x1a (important, positive-action, negative-action)
2015-01-01 20:31:08,511 INFO ANCS notification ready: app=Phone app_id=com.apple.mobilephone title='Дмитрий Попандопуло' message='Входящий' flags=important,positive-action,negative-action
2015-01-01 20:31:08,511 INFO ANCS display: app=Phone app_id=com.apple.mobilephone title='Дмитрий Попандопуло' message='Входящий' flags=important,positive-action,negative-action
2015-01-01 20:31:11,520 INFO Encoder press → ANCS positive action uid=3 app=Phone
2015-01-01 20:31:11,520 INFO ANCS positive action requested: uid=3 app=Phone app_id=com.apple.mobilephone title='Дмитрий Попандопуло'
2015-01-01 20:31:11,521 INFO ANCS perform action: uid=3 action=positive
2015-01-01 20:31:11,615 INFO ANCS source: event=2 category=1 count=0 uid=3 flags=0x1a (important, positive-action, negative-action)
2015-01-01 20:31:11,766 INFO ANCS notification ready: app=Phone app_id=com.apple.mobilephone title='Дмитрий Попандопуло' message='Активный вызов' flags=important,negative-action
```

User-visible confirmation:

- this was not just "dismiss the incoming-call banner"
- the user confirmed that pressing the button on Car Thing actually **accepted
  the incoming call**

Meaning:

1. the BLE `ANCS` path now has live proof for both directions of actionable
   notification semantics:
   - negative action (`Reminders`, timer-style notifications) -> dismiss/remove
   - positive action (`Phone` incoming call) -> accept / advance into active call
2. this is a major practical result for the no-companion architecture:
   `ANCS` is no longer merely a mirror of text, but a real control surface for
   at least some system workflows

## 2026-05-21: Life Activities Timer retest sharpened the timer boundary into a real A/B split

The next retest was not just "another timer run".

The user installed a third-party timer app that exposes a Live Activity on the
iPhone (`Life Activities Timer`) and then ran a stronger A/B comparison:

- one timer from the third-party app
- one timer from the standard Apple Timer/Clock path

Important user-visible condition:

- during the active countdown, the Live Activity was **really visible on the
  iPhone** (lock screen / Dynamic Island style surface)

Accessory-side observation during that active countdown window:

- absolutely no new `ANCS` traffic appeared
- no app-specific countdown payload appeared
- no sign of a forwarded Live Activity stream appeared

This already sharpened the boundary beyond the older generic negative test:

1. the issue is not "maybe the app never showed a Live Activity"
2. the issue is that a real visible Live Activity on iPhone still did not
   produce accessory-side traffic on the current no-app BLE path

When the third-party timer finished, the accessory did receive a final ANCS
notification:

```text
2015-01-01 20:13:58,754 INFO ANCS source: event=0 category=0 count=2 uid=1 flags=0x10 (negative-action)
2015-01-01 20:13:58,801 INFO ANCS notification ready: app=Timer app_id=com.Tobias-Hauss.Timer title='таймер 2 завершен' message='таймер истек' flags=negative-action
2015-01-01 20:13:58,801 INFO ANCS display: app=Timer app_id=com.Tobias-Hauss.Timer title='таймер 2 завершен' message='таймер истек' flags=negative-action
```

And the user then clarified an even more important comparison result:

- the third-party timer completion reached the accessory as an ANCS notification
- the standard Apple timer completion did **not** reach the accessory

Meaning:

1. this is no longer just "timers are unreliable"
2. the current iPhone/ANCS behavior is split into two materially different
   classes:
   - third-party timer app completion notification path
   - standard Apple Timer/Clock path
3. the current BLE path can surface the former, but not the latter
4. the active Live Activity itself still remains unforwarded on this path

This also lines up well with the earlier external Apple evidence already logged
for newer iPhones:

- standard `com.apple.mobiletimer` behavior through ANCS appears to have a real
  platform-specific limitation / regression on newer devices
- the new A/B result strengthens that interpretation because it shows the phone
  is **not** generically unable to forward timer completion notifications; the
  divergence is specifically between the system Clock path and the third-party
  local-notification path

The user then suggested an even tighter method: capture the **start edge**
itself, not just the running phase or the finish.

That retest was performed with the watcher already running **before** the user
created and started a fresh timer in `Life Activities Timer`, and the user
explicitly confirmed that the timer was already active on the iPhone.

Observed result:

- no new accessory-side signal appeared at creation time
- no ANCS add/update payload appeared at start time
- no delayed publish/update appeared shortly after activation
- later, only completion notifications arrived

Live excerpt:

```text
2015-01-01 20:18:14,715 INFO ANCS source: event=0 category=0 count=2 uid=3 flags=0x10 (negative-action)
2015-01-01 20:18:14,761 INFO ANCS notification ready: app=Timer app_id=com.Tobias-Hauss.Timer title='таймер 1 завершен' message='таймер истек' flags=negative-action

2015-01-01 20:18:28,110 INFO ANCS source: event=0 category=0 count=3 uid=4 flags=0x10 (negative-action)
2015-01-01 20:18:28,156 INFO ANCS notification ready: app=Timer app_id=com.Tobias-Hauss.Timer title='таймер 3 завершен' message='таймер истек' flags=negative-action
```

Meaning:

1. the negative timer boundary is now stronger than before
2. this is not merely "we did not happen to notice the running state"
3. the current no-app BLE path shows **no signal at timer creation/start**
4. it also shows **no signal during the active countdown**
5. it only surfaces the terminal third-party ANCS completion notification after
   the timer finishes

## 2026-05-21: richer ANCS attributes now expose action labels and notification dates

After the call/timer/action frontiers had been narrowed, the next code pass did
not add a new transport capability; instead it made the existing one far more
interpretable.

The ANCS client was extended to request and parse these additional notification
attributes:

- `MessageSize` (`4`)
- `Date` (`5`)
- `PositiveActionLabel` (`6`)
- `NegativeActionLabel` (`7`)

The UI/logging path was then updated so future notifications can show:

- normalized date/time
- human-readable action labels
- footer hints such as `Press:<positive>` and `Back:<negative>`

Immediate live proof came from already existing preexisting notifications on the
paired iPhone:

```text
2015-01-01 20:52:48,026 INFO ANCS notification ready: app=Feedbackassistant app_id=com.apple.appleseed.FeedbackAssistant title='Ассистент обратной связи' message='Apple отвечает на Ваш отзыв: During a phone call on eSIM1, the second line (eSIM2) is completely disconnected (loses network connection)' flags=silent,preexisting,negative-action date=2026-05-20 21:33:54 actions=Back:Очистить

2015-01-01 20:52:48,146 INFO ANCS notification ready: app=Gmail app_id=com.google.Gmail title='+7 952 371-37-10' message='Google Voice Test Чтобы ответить на сообщение, ответьте на это письмо или перейдите на сайт Google Voice. ВАШ АККАУНТ …' flags=silent,preexisting,negative-action date=2026-05-21 13:42:32 actions=Back:Очистить
```

Meaning:

1. we no longer see only the raw boolean fact that an action exists
2. we now get the iPhone-provided user-facing label for at least some actions
3. on the observed notifications, the negative action is not an abstract
   "negative" path but specifically `Очистить`
4. this makes future ANCS capability mapping much more precise:
   the next opportunistic incoming call or message can now reveal not only
   whether an action exists, but what Apple actually calls it on-screen

## 2026-05-21: Messages action semantics are now sharper than "maybe reply"

The next fresh `Messages` pass produced a much narrower and more useful result
than the older generic "Messages arrived" proof.

Observed live notification:

```text
2015-01-01 20:55:38,876 INFO ANCS source: event=0 category=4 count=1 uid=3 flags=0x10 (negative-action)
2015-01-01 20:55:38,922 INFO ANCS notification ready: app=Messages app_id=com.apple.MobileSMS title='Senior Exrector' message='Test' flags=negative-action date=2026-05-21 14:09:44 actions=Back:Очистить
2015-01-01 20:55:38,922 INFO ANCS display: app=Messages app_id=com.apple.MobileSMS title='Senior Exrector' message='Test' flags=negative-action date=2026-05-21 14:09:44 actions=Back:Очистить
```

Two immediate implications already fell out of that:

1. on this iPhone / notification style, `Messages` appears as category `4`
   (`Social`), not as a special positive-action reply path
2. the only action surfaced here was negative, with the explicit label
   `Очистить`

The follow-up live action pass then tested exactly that semantics:

```text
2015-01-01 20:58:09,507 INFO ANCS source: event=0 category=4 count=1 uid=4 flags=0x10 (negative-action)
2015-01-01 20:58:09,553 INFO ANCS notification ready: app=Messages app_id=com.apple.MobileSMS title='Senior Exrector' message='Ghbtd' flags=negative-action date=2026-05-21 14:12:14 actions=Back:Очистить
2015-01-01 20:58:14,392 INFO Back button → ANCS negative action uid=4 app=Messages
2015-01-01 20:58:14,392 INFO ANCS negative action requested: uid=4 app=Messages app_id=com.apple.MobileSMS title='Senior Exrector'
2015-01-01 20:58:14,392 INFO ANCS perform action: uid=4 action=negative
2015-01-01 20:58:14,501 INFO ANCS source: event=2 category=4 count=0 uid=4 flags=0x10 (negative-action)
2015-01-01 20:58:14,502 INFO ANCS remove active notification uid=4
```

User-visible confirmation:

- the notification also disappeared on the iPhone itself

Meaning:

1. the current `Messages` ANCS path is not yet a reply/open surface
2. on the observed notification style, it behaves as a clearable social-style
   notification
3. `Back:Очистить` is not just an accessory-local overlay hint; it really clears
   the notification on the phone
4. multiple incoming messages may still be coalesced / filtered differently:
   in one burst of three messages, only the first produced an accessory banner

The user then explicitly asked to try "another button" in case `Messages` had a
hidden path not advertised through ANCS flags. That was tested by temporarily
mapping `Button 1` to a **forced positive action**, even though the `Messages`
notification only advertised:

- `flags=negative-action`
- `actions=Back:Очистить`

Live result:

```text
2015-01-01 21:03:19,305 INFO ANCS notification ready: app=Messages app_id=com.apple.MobileSMS title='Senior Exrector' message='Буй' flags=negative-action date=2026-05-21 14:17:27 actions=Back:Очистить
2015-01-01 21:03:20,232 INFO Button 1 → ANCS forced positive action uid=2 app=Messages
2015-01-01 21:03:20,232 INFO ANCS forced positive action requested: uid=2 app=Messages app_id=com.apple.MobileSMS title='Senior Exrector' flags=negative-action actions=Back:Очистить
2015-01-01 21:03:20,233 INFO ANCS perform action: uid=2 action=positive
...
bumble.core.ProtocolError: ProtocolError(att/[0xA3] [0xA3])
```

User-visible confirmation:

- nothing happened on the iPhone

Meaning:

1. the missing `positive-action` on this `Messages` notification is not just a
   UI omission in our code
2. forcing a raw positive ANCS action is actively rejected by the iPhone stack
   for this notification
3. therefore the current `Messages` path is not secretly one button away from
   reply/open semantics
4. after the experiment, `Button 1` was restored to its normal non-notification
   behavior so the runtime does not keep a noisy failing probe mapped into
   regular use
