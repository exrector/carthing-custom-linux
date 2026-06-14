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

## 2026-05-20: `0x4E` priming narrowed to the minimal challenge-side event

The remaining auth-chip ambiguity was no longer "does `0x4E` ever work?".
That part was already proven. The missing piece was much narrower:

- what is the *minimal* event that makes the historical `0x4E` path usable
- what clears that state again without a full reboot

New probe commands added for this pass:

- `carthing-mfi-probe raw-prime-21-challenge-only <challenge_hex>`
- `carthing-mfi-probe raw-prime-start-only`
- `carthing-mfi-probe raw-prime-21-start-no-poll <challenge_hex>`
- `carthing-mfi-probe raw-prime-21-start-poll-once <challenge_hex>`
- `carthing-mfi-probe raw-prime-21-start-sleep <challenge_hex> <sleep_ms>`

### Minimal priming result

Reboot-isolated scenarios showed:

1. `0x21 challenge write` **alone** is already enough to make the next `0x4E`
   sign attempt succeed.
2. `0x10=0x01` **without** a preceding `0x21` challenge write does **not** prime
   `0x4E`.
3. `0x21 + 0x10=0x01` with no poll, with a single poll, and with a short sleep
   all also prime `0x4E`, but they are no longer the minimal trigger.

This is the decisive correction to the earlier hypothesis. `0x4E` does **not**
need a full successful completion of the canonical sign flow before it becomes
usable. The minimal enabling event is already on the challenge side.

### Reboot-isolated proofs

1. Clean boot -> `raw-prime-21-challenge-only` -> `raw-sign-trace-4e`

- `0x4E` succeeds:
  - `poll[1]=nack`
  - `poll[2]=0x10`
  - `error_code=0x00`
  - `siglen=0x0040`
  - `ready=yes`

2. Clean boot -> `raw-prime-start-only` -> `raw-sign-trace-4e`

- `0x4E` fails exactly like the old cold-boot path:
  - repeated `poll[*]=0x80`
  - `error_code=0x05`
  - `siglen=0x0000`
  - `ready=no`

Meaning:

- `0x10=0x01` is **not** the hidden enabling event
- the hidden enabling event sits at or before the canonical `0x21` challenge
  write

### What does *not* clear the primed state immediately

Clean boot -> `raw-prime-21-challenge-only` -> `raw-prime-start-only` ->
`raw-sign-trace-4e`

- `0x4E` still succeeds

Clean boot -> `raw-prime-21-challenge-only` -> `raw-info` ->
`raw-sign-trace-4e`

- `0x4E` still succeeds

Meaning:

- a later bare start command does not undo the primed state
- a plain prepare/info walk (`0x00`, `0x01`, simple reads) does not undo it

### What *does* clear the primed state

Clean boot -> `raw-prime-21-challenge-only` -> `raw-cert-trace` ->
`raw-sign-trace-4e`

- `0x4E` falls back to the cold-boot failure path:
  - repeated `poll[*]=0x80`
  - `error_code=0x05`
  - `siglen=0x0000`
  - `ready=no`

The same reset behavior also appears after a *full* canonical sign-side prime:

Clean boot -> `raw-prime-21-no-readout` -> `raw-cert-trace` ->
`raw-sign-trace-4e`

- `0x4E` again fails with `0x80 / error=0x05 / siglen=0x0000`

Meaning:

- the certificate path is not just orthogonal to the compatibility window
- it actively clears or reinitializes the hidden state that makes `0x4E`
  usable

### The primed `0x4E` window is temporary

Clean boot -> `raw-prime-21-challenge-only` -> `sleep 1` ->
`raw-sign-trace-4e`

- success

Clean boot -> `raw-prime-21-challenge-only` -> `sleep 2` ->
`raw-sign-trace-4e`

- success

Clean boot -> `raw-prime-21-challenge-only` -> `sleep 5` ->
`raw-sign-trace-4e`

- failure (`0x80 / error=0x05 / siglen=0x0000`)

The same timeout behavior also holds after the stronger canonical prime:

Clean boot -> `raw-prime-21-no-readout` -> `sleep 5` ->
`raw-sign-trace-4e`

- failure (`0x80 / error=0x05 / siglen=0x0000`)

Meaning:

- the `0x4E` compatibility window persists for at least a short interval
- it survives 1-2 seconds
- it does **not** survive an idle gap of 5 seconds
- the window is therefore transient even after a stronger sign-side prepare

### Updated low-level contract

The current best clean-room model is now:

- canonical sign path:
  - write challenge to `0x21`
  - start with `0x10 0x01`
  - poll `0x10`
  - read `0x11/0x12`
- historical `0x4E` path:
  - not a canonical primary backend
  - not a purely completion-dependent alias
  - a **challenge-side, transient, state-dependent compatibility window**
  - cleared by cert-path activity
  - cleared by idle timeout somewhere between 2 and 5 seconds

Practical implication for the project:

- never build higher layers assuming `0x4E` is the stable backend
- treat `0x21` as the real primitive we control
- if compatibility with historical `0x4E` is ever needed, it must be modeled as
  an ephemeral side effect, not as the main contract

This is important for the broader user goal: making the auth chip stop being a
project blocker. The path to that is not "make `0x4E` reliable". The path is to
fully own the canonical `0x21` contract and treat everything else as legacy or
compatibility behavior layered on top of it.

## 2026-05-20: `0x4E` does not sign its own challenge, it signs the last latched `0x21` challenge

The next unresolved question was subtle but critical:

- after `raw-prime-21-challenge-only`, does a later `0x4E` operation sign the
  new bytes written through `0x4E`
- or does it keep using challenge material latched earlier by `0x21`

Reboot-isolated challenge-binding tests answered this decisively.

### Test A: prime with challenge `A`, then ask `0x4E` to sign challenge `B`

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-sign-trace-4e B`

Observed result:

- `0x4E` succeeds
- returned signature verifies against `A`
- returned signature does **not** verify against `B`

Meaning:

- the `0x4E` write bytes are not the real message being signed here
- the meaningful challenge payload is already latched by the earlier canonical
  `0x21` write

### Test B: one prime, then two consecutive `0x4E` signatures

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-sign-trace-4e A`
- `raw-sign-trace-4e B`

Observed result:

- first `0x4E` succeeds and verifies against `A`
- second `0x4E` also succeeds
- second `0x4E` still verifies against `A`, not `B`

Meaning:

- one compatibility window can serve more than one `0x4E` request
- the window is not single-use
- the challenge latch survives at least one successful `0x4E` sign

### Test C: reuse after delay inside the same window

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-sign-trace-4e A`
- `sleep 1`
- `raw-sign-trace-4e B`

Observed result:

- the second `0x4E` still succeeds
- its signature still verifies against `A`, not `B`

Meaning:

- the challenge latch is persistent for the life of the compatibility window
- it is not rewritten by successful `0x4E` traffic itself

### Test D: replace the latch with a second canonical `0x21` write

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-prime-21-challenge-only B`
- `raw-sign-trace-4e C`

Observed result:

- `0x4E` succeeds
- signature verifies against `B`
- signature does **not** verify against `A` or `C`

The same replacement also works after an intermediate successful `0x4E` sign:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-sign-trace-4e A`
- `raw-prime-21-challenge-only B`
- `raw-sign-trace-4e C`

Observed result:

- final `0x4E` succeeds
- final signature verifies against `B`

Meaning:

- the active compatibility challenge is always the **most recent canonical
  `0x21` challenge write**
- a new `0x21` write refreshes the window and replaces the latched payload
- `0x4E` is therefore not an independent sign command at all on this image; it
  behaves like a state-dependent accessor into a pre-latched canonical challenge

### Timeout boundary narrowed further

The first timeout pass only proved:

- success after 1-2 seconds
- failure after 5 seconds

The tighter boundary tests now show:

- success after 3 seconds
- failure after 4 seconds

So on the current working image, the `0x4E` compatibility window expires
somewhere between **3 and 4 seconds** after the last relevant `0x21` priming
write.

### Updated best model of `0x4E`

The current clean-room model is now much sharper:

- `0x21` is the canonical challenge ingress
- that write latches the challenge payload into internal auth state
- for a short period after that, `0x4E` can trigger signature production
  against the **latched** canonical challenge
- `0x4E` input bytes are not authoritative challenge material on this image
- the compatibility window:
  - can be reused more than once
  - can be refreshed/replaced by a new `0x21` challenge write
  - expires between 3 and 4 seconds
  - is cleared by cert-path activity

This changes the practical interpretation again:

- `0x4E` is not merely "a weaker sign path"
- it is closer to a transient compatibility trigger over already-latched
  canonical state
- any future stable backend must therefore be designed around `0x21`, with
  `0x4E` treated as an implementation curiosity or legacy shim rather than a
  supported primitive

## 2026-05-20: canonical `0x21` path bottomed further — same challenge latch, same timeout class, refresh on successful sign

After the `0x4E` contract became clear, the next question was whether the
canonical `0x21` path was actually much more durable, or whether it shared the
same hidden state machine and timeout rules.

For this pass, the probe gained one more narrow mode:

- `carthing-mfi-probe raw-start-readout`

This mode does **not** write a new challenge. It only:

- performs the usual `0x00` / `0x01` prepare
- writes `0x10 0x01`
- polls `0x10`
- reads `0x11` and `0x12`

That makes it possible to test the already-latched canonical challenge state
without rewriting `0x21`.

### Canonical challenge latch is real

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-start-readout`

Observed result:

- success
- returned signature verifies against `A`

Meaning:

- the canonical challenge payload really is latched by `0x21`
- a later start/readout can consume that latched state without rewriting the
  challenge first

### Canonical latch lifetime without refresh

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `sleep 3`
- `raw-start-readout`

Observed result:

- success
- signature verifies against `A`

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `sleep 4`
- `raw-start-readout`

Observed result:

- failure:
  - repeated `poll[*]=0x80`
  - `error_code=0x05`
  - `siglen=0x0000`
  - `ready=no`

The looser 5-second and 15-second tests also fail the same way.

Meaning:

- the canonical latched challenge is also transient
- with no further successful sign-side activity, it expires between **3 and 4
  seconds**
- this is the same timeout class already observed around the `0x4E`
  compatibility window

### Canonical path is reusable inside the window

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-start-readout`
- `raw-start-readout`

Observed result:

- both sign attempts succeed
- both signatures verify against `A`

Meaning:

- canonical start/readout is not single-use
- one latched challenge can drive multiple canonical signatures while the window
  remains active

### Successful sign activity refreshes the canonical window

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `sleep 3`
- `raw-start-readout`
- `sleep 1`
- `raw-start-readout`

Observed result:

- the final sign still succeeds
- final signature still verifies against `A`

This matters because without refresh, the same overall age would already be past
the failure boundary found above.

Meaning:

- a successful canonical sign does not merely consume the latch
- it refreshes or extends the active sign-side window while preserving the same
  latched challenge payload

### `0x4E` also preserves and refreshes the canonical sign state

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `sleep 3`
- `raw-sign-trace-4e A`
- `sleep 1`
- `raw-start-readout`

Observed result:

- final canonical start/readout succeeds
- final signature verifies against `A`

Meaning:

- a successful `0x4E` operation does not consume or corrupt canonical `0x21`
  state
- it appears to refresh the same underlying transient sign window

### cert-path clears canonical sign state too

Flow:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-cert-trace`
- `raw-start-readout`

Observed result:

- failure (`0x80 / error=0x05 / siglen=0x0000`)

The same reset happens after a full successful canonical sign:

- clean boot
- `raw-prime-21-challenge-only A`
- `raw-start-readout`
- `raw-cert-trace`
- `raw-start-readout`

Observed result:

- failure again (`0x80 / error=0x05 / siglen=0x0000`)

Meaning:

- cert-path does not just clear the `0x4E` compatibility view
- it clears the underlying canonical sign-side state itself

### Updated best model of the auth chip

The current clean-room model is now:

- `0x21` writes the authoritative challenge into internal sign state
- that challenge remains latched for a short idle window
- `0x10 0x01` is the canonical trigger that turns the latched challenge into a
  signature
- successful sign-side activity can refresh the active window without replacing
  the latched challenge
- `0x4E` rides on top of the same underlying latched sign state
- cert-path reinitializes or clears that sign state

### Practical consequence for making the chip non-blocking

This is the most important architectural consequence so far:

- the chip is no longer a mystery device with multiple equally plausible paths
- it now looks like one canonical sign state machine with:
  - one authoritative challenge ingress (`0x21`)
  - one canonical trigger (`0x10 0x01`)
  - one transient active window (roughly 3-4 seconds of idle lifetime)
  - one reset/clear path (cert-side activity)
  - one historical compatibility trigger layered on top (`0x4E`)

That is close to the level needed for a real reusable backend. The remaining
work is no longer "what does the chip basically do?" but "how do we wrap this
state machine into a helper/service so upper layers never need to care about the
timing/reset quirks again?"

## Implementation handoff for the next agent

This section is intentionally written as a practical handoff for an implementation
agent. The goal is **not** to continue archaeology. The goal is to build a
reusable backend/helper so upper layers stop depending on raw chip quirks.

### What is already stable enough to treat as the contract

For the current working image, the following should be treated as the source of
truth:

- the auth chip is reachable over:
  - `/dev/i2c-3`
  - slave address `0x10`
- the only production-worthy challenge ingress is:
  - `0x21`
- the only production-worthy sign trigger is:
  - write `0x10 0x01`
- the only production-worthy sign readout is:
  - status from `0x10`
  - length from `0x11`
  - signature bytes from `0x12`
- the certificate path is:
  - prepare
  - `0x31`
  - read 16-byte chunks

### What must *not* be treated as the contract

Do **not** build a new backend around any of the following:

- `0x4E` as a primary sign path
- old `/dev/apple_mfi` ioctl behavior as the active contract on this image
- SMBus byte/word probes as authoritative post-command state
- persistence of sign state across long idle gaps
- coexistence of cert reads and sign state without reset handling

`0x4E` is now best understood as a temporary compatibility trigger over state
already latched by canonical `0x21`. It is useful for reverse engineering and
comparative diagnostics. It is **not** the backend another agent should
implement.

### Canonical sign transaction the next agent should implement

Recommended unit of work: **one self-contained sign transaction per request**.

For each sign request:

1. Open `/dev/i2c-3`
2. Select address `0x10`
3. Run prepare:
   - short write `0x00`
   - short write `0x01`
4. Write the 32-byte challenge through:
   - `0x21 + digest32`
5. Trigger signing through:
   - `0x10 0x01`
6. Poll `0x10` until it becomes `0x10`
   - early `nack` is normal
7. Read:
   - `0x05` error code, expect `0x00`
   - `0x11` signature length, expect `0x0040`
   - `0x12` 64-byte signature
8. Close the fd

Important implementation note:

- the signed input is the already prepared **32-byte SHA-256 digest**
- verification succeeds as **ECDSA over prehashed SHA-256**
- do **not** hash the 32-byte challenge again when validating behavior

### Canonical cert transaction the next agent should implement

Recommended unit of work: **one self-contained cert transaction per request**.

For each cert request:

1. Open `/dev/i2c-3`
2. Select address `0x10`
3. Run prepare:
   - short write `0x00`
   - short write `0x01`
4. Start cert streaming with:
   - short write `0x31`
5. Read the first 16-byte chunk
6. Parse ASN.1 total length and round to the known 16-byte chunking
7. Continue reading until the whole PKCS#7 blob is collected
8. Close the fd

### State rules the implementation agent must internalize

1. `0x21` latches the authoritative challenge payload.
2. A later canonical start/readout can use that latch without rewriting
   challenge.
3. The sign-side state has a transient idle window:
   - success at 3 seconds
   - failure at 4 seconds
4. Successful sign-side activity refreshes that window.
5. cert-path clears the sign-side state.
6. `0x4E` uses the same underlying state but should be treated as diagnostic-only.

### The most important implementation consequence

The backend does **not** need to keep this sign state alive.

The safest architecture is:

- always rewrite `0x21` on every sign request
- always run the full canonical transaction from scratch
- never assume any previously latched state is still valid

In other words, the discovered 3-4 second window is important for understanding
the chip, but a robust backend should make that window almost irrelevant by
treating requests as fresh transactions.

### Recovery rules that are already proven

The implementation agent can rely on the following recovery behavior:

- after idle-timeout failure (`0x80 / error=0x05 / siglen=0x0000`), a fresh
  canonical `0x21` challenge write followed by canonical start/readout recovers
  without reboot
- after `raw-prime-start-only` / bad start-side state, a fresh canonical
  transaction recovers without reboot
- after cold `0x4E` failure, a fresh canonical transaction recovers without
  reboot
- after cert-path reset, a fresh canonical transaction recovers without reboot
- after cert-path reset *following a successful sign*, a fresh canonical
  transaction still recovers without reboot

This is the critical reason the chip is now close to becoming non-blocking for
other project work: even though the state machine is timing-sensitive, it is not
reboot-fragile. A helper can recover from all known failure/reset modes by
starting a new canonical transaction.

### Concurrency and process model

Another agent implementing the backend should assume:

- chip access must be serialized
- cert and sign operations share mutable internal chip state
- cert reads and sign operations must not overlap

Recommended backend shape:

- one helper process or one library object with a mutex
- request types:
  - `read_cert() -> pkcs7`
  - `sign_digest(digest32) -> sig64`
- no shared long-lived sign latch exposed to callers
- no caller-visible `prime` concept
- no caller-visible `0x4E`

### Suggested error-handling policy

On sign:

- if poll/readout does not converge to:
  - `status=0x10`
  - `error=0x00`
  - `siglen=0x0040`
- discard that transaction
- close fd
- retry from the beginning with a fresh canonical transaction

If the retry still fails, surface a real error instead of pretending the chip is
fine.

On cert:

- if the stream is malformed or truncated, discard that transaction and retry
  from scratch

No broad silent fallbacks should be used.

### Acceptance checks for the implementation agent

A new backend/helper should not be considered done until it can reproduce all of
the following:

1. `read_cert()` returns the live PKCS#7 blob and wraps cleanly into `AA01`.
2. `sign_digest(A)` returns a 64-byte signature verifying against the live leaf
   public key.
3. Repeated `sign_digest(A)` calls succeed even if there is more than 4 seconds
   between calls, because each call rewrites `0x21` and runs a fresh transaction.
4. A cert request between two sign requests does not break the next sign request,
   because the next sign request rewrites challenge and restarts canonical flow.
5. No production path depends on `0x4E`.

### Files and artifacts the implementation agent should read first

Project source of truth:

- `buildroot-external/package/carthing-mfi-probe/src/carthing-mfi-probe.c`
- this document: `docs/mfi-low-level-probe-2026-05-18.md`

Useful preserved artifacts from this session:

- `.../files/signature-lab/pubkey.pem`
- `.../files/signature-lab/raw-sign-repeats.txt`
- `.../files/priming-lab/`

The artifact directory is useful for verifying the exact timeout/recovery traces,
but the implementation should be based on the canonical contract above rather
than on replaying the experimental `0x4E` paths.

## 2026-05-20: second-device classic trust and accepted iAP2 path now prove the blocker is above auth

The next live round moved deliberately off the main working device and onto a
second identical unit so aggressive tests would not interfere with the primary
development flow.

The user also made the iPhone side much more cooperative:

- phone unlocked
- Apple Music available for live triggering
- willing to accept pairing/trust prompts and report exact UI behavior

### Classic trust/key was the real gate before higher iAP2 progress

With a unique classic test identity:

- `CarThing Test iAP2`

the iPhone saw the device in Bluetooth settings, the user tapped it, approved
the trust/access prompt, and the accessory entered the trusted list as
`not connected`.

That action created the first reusable BR/EDR link key on the device:

```text
10:A2:D3:83:82:50 a2344284cc3f706300d935f7cb57b904 04
```

Before that trust event, the daemon always produced:

- `LINK_KEY_REQ -> negative`
- `AUTH COMPLETE status=0x05`

After the trust event, the daemon could answer:

- `LINK_KEY_REQ -> cached reply type=0x04`
- `AUTH COMPLETE status=0x00`

Meaning:

- the next real blocker above the auth chip was classic trust/key state
- once that existed, the clean-room iAP2 path could finally move past SSP/auth

### Full stack with live helper now reaches AA auth and Identification start

After deploying both:

- `carthing-iap2-mini`
- `carthing-mfi-probe` via `CARTHING_MFI_HELPER`

the active classic path reached:

- `AA00`
- `AA02`
- `AA05`
- `1D00`

This is the first direct live proof on the second device that:

- the classic path can authenticate end-to-end with the real iPhone
- the clean-room stack can carry real iAP2 control traffic above MFi auth

### Non-empty `0x0006/0x0007` are now proven to cause live `1D03`

When `IdentificationInformation` advertised:

- `0x0006 = { 0x40C8, 0x40C9 }`
- `0x0007 = { 0x4800 }`

the iPhone rejected identification with:

```text
1D03 rejected param id=0x0006
```

This is important because the preserved notes had already suggested that
`SupportedMessageIDs` should be empty. The new live run now proves it in the
fully authenticated path on the second device.

### Empty `0x0006/0x0007` plus omitted `0x000A` produce the first clean accepted path

When the daemon switched to:

- omit `0x000A`
- empty `0x0006`
- empty `0x0007`

the iPhone accepted:

```text
AA00 -> AA02 -> AA05 -> 1D00 -> 1D02
```

and the daemon successfully sent:

- `0x6800 StartHID`
- `0x40C8 StartNowPlayingUpdates`

This is now the best clean-room accepted identification path observed live on
the second device.

### Apple Music still does not yield `0x4800`

After that accepted path was up, the user triggered Apple Music playback change
(`play/pause`).

Observed result:

- no `0x4800 NowPlayingUpdate`
- no additional useful incoming iAP2 control message beyond the already accepted
  path

This continues to match the earlier preserved note:

- Apple Music may accept `StartNowPlayingUpdates`
- but it still does not actually emit `0x4800` in this iAP2 path

### Updated current blocker for Codex / implementation work

The current frontier is now sharply narrowed:

- not the MFi auth chip
- not classic trust, once the BR/EDR link key exists
- not AA auth
- not `1D00`
- not `0x000A`, once omitted

The current blocker is now specifically:

- accepted `IdentificationInformation` semantics above auth
- especially the fact that non-empty `0x0006/0x0007` trigger `1D03`
- and the fact that even on the accepted path, Apple Music still does not
  provide `0x4800`

So the new search space is much smaller:

- refine post-`1D02` contract
- determine what useful traffic is actually available on this path
- stop treating the auth chip as the active blocker for current iAP2 work

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

## 2026-05-20: dedicated chip-trace commands added and run on the live auth chip

The next low-level step was to stop relying on one successful `raw-sign` path and
add explicit chip-side trace modes to `carthing-mfi-probe`:

- `raw-cert-trace`
- `raw-sign-trace <challenge_hex>`

These new modes stay below iAP2/session logic and print the chip's low-level
state transitions directly from `/dev/i2c-3`.

What the live `raw-cert-trace` run showed on the current working image:

```text
[initial]
smbus_reg00=na
...
plain_reg00_4=07010300
plain_reg10=00
rdwr_reg10=00
plain_reg11=0000
rdwr_reg11=0000
short_0x00=ok
[after_short_00]
smbus_reg00=0x07
...
smbus_reg30w=0x0107
short_0x01=ok
[after_short_01]
smbus_reg00=0x01
...
smbus_reg30w=0x0301
short_0x31=ok
cert_chunk0=3082025c06092a864886f70d010702a0
cert_total_len=608
[after_cert_chunk0]
smbus_reg00=0x30
...
smbus_reg30w=0x8230
plain_reg00_4=07010300
```

Meaning:

- before explicit prepare, the SMBus byte/word helpers are not a reliable view of
  the chip state yet, but the plain `write(reg) + read()` transport already
  returns the stable identity tuple `07 01 03 00`
- after short writes `0x00` and `0x01`, the SMBus byte/word helpers mirror the
  visible phase bytes we already knew
- after the cert command `0x31`, the SMBus helpers mostly reflect the last
  command latch (`0x30` / `0x8230`), while the plain transport still reports the
  stable chip identity tuple

This is a concrete new boundary:

- the plain `open/write/read` path is the authoritative low-level transport for
  chip-state inspection
- SMBus byte/word reads are useful as a coarse phase probe, but they are not a
  trustworthy semantic register view after command-style operations

What the live `raw-sign-trace` run showed for challenge `00..1f`:

```text
[initial]
smbus_reg00=0x00
...
plain_reg00_4=07010300
short_0x00=ok
[after_short_00]
smbus_reg00=0x07
...
short_0x01=ok
[after_short_01]
smbus_reg00=0x01
...
write_0x21_challenge=ok
[after_challenge_write]
smbus_reg00=0x00
...
write_0x10_0x01=ok
poll[1]=nack
poll[2]=nack
poll[3]=0x10
[after_poll]
smbus_reg00=0x10
plain_reg10=10
rdwr_reg10=10
plain_reg11=0040
rdwr_reg11=0040
error_code=0x00
siglen_raw=0040
siglen=0x0040
signature=<64-byte value>
ready=yes
```

Meaning:

- after the contiguous challenge write to `0x21`, the coarse SMBus view drops
  back to `0x00` until the explicit start command is issued
- the actual sign readiness still follows the same working sequence:
  - write `0x21 + 32 challenge bytes`
  - write `0x10 0x01`
  - tolerate `nack` during the early poll window
  - wait for status `0x10`
  - then read `0x11` / `0x12`
- once the chip reaches the ready state, both read transports agree on the
  important post-prepare registers:
  - plain `write(reg)+read`
  - repeated-start `I2C_RDWR`

This sharpens the low-level conclusion again:

- repeated-start reads are not universally "wrong"
- the real issue was earlier in the command-style wake/arming sequence
- after the chip is properly armed, repeated-start reads of `0x10` and `0x11`
  match the plain transport on the live device

Updated auth-chip frontier after these traces:

- live cert path is proven
- live sign path is proven
- wake/prepare transitions are now instrumented directly in our own helper
- the plain transport vs SMBus-helper distinction is now explicit instead of
  inferred
- the remaining auth-chip work is now mostly polish and targeted edge-case
  mapping, not basic register-family ambiguity anymore

## 2026-05-20: old `/dev/apple_mfi` contract and live raw-I2C contract are now explicitly separated

The next useful comparison was not another live trace, but a cross-check against
the preserved older reverse-engineering notes and public-facing project mirrors.

Those older materials consistently describe the historical kernel-driver view as:

- cert length at `0x30`
- cert data at `0x31`
- challenge write at `0x4E`
- signature read at `0x12`
- sleep handling hidden behind the old `/dev/apple_mfi` ioctl path

That older picture still matters, but after the current live traces it should no
longer be treated as the same thing as the active direct-I2C path on the custom
image.

What the current low-level evidence now supports:

- the old kernel/ioctl contract may well have written challenge data through
  `0x4E`
- but the live direct `/dev/i2c-3` path that actually works on the current image
  signs through:
  - contiguous write `0x21 + 32 challenge bytes`
  - contiguous write `0x10 0x01`
  - tolerate early poll `nack`
  - wait for status `0x10`
  - read `0x11` / `0x12`

So the clean-room rule is now sharper:

- do not collapse "old `/dev/apple_mfi` semantics" and "current raw-I2C chip
  semantics" into one assumed register contract
- preserve `0x4E` as a historical driver-side fact
- preserve `0x21 + 0x10` as the proven live direct-I2C sign path on the current
  image

Practical implication for future work:

- if `/dev/apple_mfi` is ever restored, it should be treated as a separate
  compatibility backend with its own documented semantics
- the clean-room backend should continue to treat the raw-I2C path as the source
  of truth for the live custom image unless new evidence proves that the old
  `0x4E` path can also be made to work directly on this chip without the missing
  kernel-side translation layer

## 2026-05-20: direct `0x4E` path is real but state-dependent on the live raw-I2C backend

The next isolated experiment added a second low-level sign trace mode:

```text
carthing-mfi-probe raw-sign-trace-4e <challenge_hex>
```

This uses the same direct-I2C trace harness as `raw-sign-trace`, but writes the
32-byte challenge to `0x4E` instead of `0x21`.

Two live runs against the same challenge exposed a much narrower result than the
old binary distinction of "works" vs "does not work".

### Run A: `0x21` first, then `0x4E`

Observed result:

- `0x21` path reached the known-good ready state:
  - early poll `nack`
  - then status `0x10`
  - `error_code=0x00`
  - `siglen=0x0040`
  - non-zero 64-byte signature
- the later `0x4E` run in the same overall session also reached:
  - status `0x10`
  - `error_code=0x00`
  - `siglen=0x0040`
  - non-zero 64-byte signature

### Run B: `0x4E` first from a clean initial state

Observed result:

- after `0x4E` challenge write, plain status moved to `0x80`
- after start `0x10 0x01`, the chip stayed at:
  - `poll[*]=0x80`
  - `error_code=0x05`
  - `siglen=0x0000`
  - zero-padded signature buffer
- a following `0x21` run immediately restored the known-good path and reached:
  - status `0x10`
  - `error_code=0x00`
  - `siglen=0x0040`
  - valid non-zero signature output

Meaning:

- the direct `0x4E` path is not simply "wrong" on the live chip
- but it is also not a standalone reliable replacement for the proven `0x21`
  path on the current custom image
- the currently observed behavior is:
  - `0x21` is the only direct raw-I2C path proven reliable from a clean state
  - `0x4E` can produce a success-shaped result only in some prior-state
    conditions
  - from a clean state, `0x4E` still reproduces the older failure signature:
    `0x80` + `error_code=0x05`

So the clean-room conclusion is now more precise:

- keep `0x21 + 0x10` as the canonical direct-I2C sign path
- keep `0x4E` as a historically meaningful register that may reflect the old
  kernel-driver contract or an alternate internal mode
- do not yet promote `0x4E` to a supported raw-I2C signing backend on the custom
  image

Updated frontier:

- the remaining low-level question is no longer "does `0x4E` exist at all?"
- it is now:
  - what hidden state makes `0x4E` sometimes succeed after a prior successful
    sign flow
  - whether that state came from the old kernel translation layer, a latched chip
    mode, or a transport-side sequencing difference we still have not isolated

## 2026-05-20: direct-I2C signatures are valid but not deterministic

The next deep check moved past transport behavior and tested the signatures
cryptographically against the live chip certificate.

Method:

- read `AA01` live from the chip
- extract the embedded leaf certificate and public key
- collect five repeated direct-I2C `raw-sign` results for the same challenge
- verify each raw 64-byte `r||s` signature against the challenge using the leaf
  public key

Observed result:

- all five repeated `0x21`-path signatures were different
- all five verified successfully as:
  - ECDSA over a prehashed 32-byte SHA-256 digest
- the same signatures did **not** verify as "hash the 32-byte challenge again
  with SHA-256 first"

Practical meaning:

- the chip is not producing a deterministic signature for the same challenge on
  the direct-I2C path
- but the signatures are still cryptographically valid for the same leaf key
- so a "different signature for the same challenge" is not, by itself, evidence
  of a bad path on this chip

This removes one earlier ambiguity:

- the fact that a later `0x4E` success-shaped run returned a different signature
  than a preceding `0x21` run is not suspicious by itself
- the correct test is validity against the chip certificate, not byte-for-byte
  equality

## 2026-05-20: reboot-isolated proof that `0x4E` is primed by sign flow, not by cert flow

The remaining question after the state-dependent `0x4E` result was:

- does `0x4E` become usable after any auth-chip activity?
- or only after a successful direct sign flow?

To isolate that, three reboot-separated scenarios were run. After each reboot,
the probe binary was re-uploaded and only one preparation path was allowed before
`raw-sign-trace-4e`.

### Scenario A: clean boot -> `0x4E`

Observed result:

- `ready=no`
- `error=0x05`
- `poll[*]=0x80`
- no valid signature

### Scenario B: clean boot -> `AA01` / cert read -> `0x4E`

Observed result:

- `ready=no`
- `error=0x05`
- `poll[*]=0x80`
- no valid signature

### Scenario C: clean boot -> one successful `0x21` sign -> `0x4E`

Observed result:

- `ready=yes`
- `error=0x00`
- status reached `0x10` after three polls
- the resulting `0x4E` signature verified correctly against the live leaf key

Meaning:

- cert-path activity alone does **not** prime the live direct-I2C `0x4E` path
- one successful `0x21` sign flow **does** prime it
- the hidden state required by `0x4E` is therefore tied to the sign-side state
  machine, not just to generic wake-up or certificate access

Updated low-level rule:

- canonical direct-I2C sign path remains:
  - `0x21 + 32-byte challenge`
  - `0x10 0x01`
  - poll for `0x10`
  - read `0x11` / `0x12`
- `0x4E` is now best treated as a secondary, sign-state-dependent path that only
  becomes usable after the canonical sign path has already completed at least once

## 2026-05-20: `0x4E` priming does not require reading the signature buffer

The next remaining ambiguity was whether `0x4E` becomes usable only after a full
successful sign transaction, or whether the decisive step is earlier in the sign
engine state machine.

To isolate that, one more reboot-separated scenario was added:

### Scenario D: clean boot -> `raw-prime-21` -> `0x4E`

`raw-prime-21` drives the canonical `0x21` path to the ready state and reads
`0x11`, but still does not read `0x12`.

Observed result:

- the following `0x4E` run succeeded
- it reached `ready=yes`
- `error=0x00`
- returned a signature that verified correctly against the live leaf key

### Scenario E: clean boot -> `raw-prime-21-no-readout` -> `0x4E`

`raw-prime-21-no-readout` goes one step lower:

- write `0x21 + challenge`
- write `0x10 0x01`
- poll until the chip reaches the ready state
- do **not** read `0x11`
- do **not** read `0x12`

Observed result:

- the following `0x4E` run still succeeded
- it reached `ready=yes`
- `error=0x00`
- status reached `0x10` after two polls
- the resulting `0x4E` signature again verified correctly against the live leaf
  key

Meaning:

- the priming event happens before signature-buffer readout
- reading `0x11` is not required
- reading `0x12` is not required
- the decisive state transition is the canonical `0x21` sign engine reaching its
  ready/complete state

This narrows the remaining low-level question further:

- `0x4E` is not gated by "certificate was read"
- `0x4E` is not gated by "signature bytes were read back"
- `0x4E` is gated by the underlying sign-side state machine having already been
  armed successfully through the canonical `0x21` path
