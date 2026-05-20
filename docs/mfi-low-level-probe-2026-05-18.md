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

### Meaning

This moves the current app-launch / EA frontier one layer lower:

1. The iPhone accepts the current autonomous path only when `1D01` keeps
   `MessagesSentByAccessory (0x0006)` and `MessagesReceivedFromDevice (0x0007)`
   empty.
2. As soon as the probe advertises any of the current handcrafted message-set
   variants (`EA02-only`, `hid-nowplaying`, or the hybrid), identification is
   rejected before `1D02`.
3. Therefore the present blocker for `EA02` is **not yet** "does iPhone launch
   the app?" but rather:
   - what exact encoding/semantics Apple expects for `0x0006` / `0x0007`
   - whether the current byte-array representation is incomplete or wrong for
     this iPhone path

Practical consequence:

- do **not** interpret the current `EA02` result as "app launch is impossible"
- the honest current statement is narrower:
  - our current `1D01` message-set encoding is rejected by the iPhone
  - until that encoding is fixed, `EA02` cannot be tested fairly on this path
