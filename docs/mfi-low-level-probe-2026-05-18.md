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
