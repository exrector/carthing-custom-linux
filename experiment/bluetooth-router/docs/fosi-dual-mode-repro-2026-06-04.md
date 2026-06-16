# Fosi + iPhone Dual-Mode Reproduction Runbook

Date: 2026-06-04

This note exists because the Fosi/A2DP/AVRCP facts were previously buried in
agent session logs. Do not treat a JSON trusted-device row as proof of pairing.
For Fosi, the physical proof is classic link-key + encrypted ACL + SDP service
scan + AVDTP open/start.

## Known Facts

- Fosi address: `C4:A9:B8:70:2F:E5`.
- Fosi display name used in the project: `Fosi Audio ZD3`.
- Old live SDP scan found these service UUIDs:
  - `0x110B` = A2DP Audio Sink.
  - `0x110A` = A2DP Audio Source.
  - `0x110E` / `0x110F` = AVRCP target/controller.
  - `0x111E` was not found.
- This means Fosi is not only an audio output. It is also a control-capable
  classic device and must keep the `remote-control` / `classic_avrcp` endpoint.
- The proven A2DP path is:
  `connect -> SSP -> encrypt=True -> SDP AVDTP version -> AVDTP connect -> discover endpoints -> sink -> open -> start`.
- The old successful standalone marker was `A2DP_STREAMING_OK`.

## iPhone Dual-Mode Contract

The iPhone side must be one logical dual-mode device, not two user-visible
personalities:

- BLE is used for the remote/control/metadata side: AMS, ANCS, CTS, HID/GATT.
- Classic BR/EDR is used for A2DP and AVRCP.
- BLE pairing must use Secure Connections + CTKD so one iPhone bond stores
  `ltk`, `irk`, and classic `link_key` in the same keystore identity.
- A classic-only iPhone bond is broken for this project. Symptom: the iPhone
  entry in `keys.json` has only `link_key`, without `ltk`/`irk`.
- A2DP Sink SDP and AVRCP Target SDP must be present before iPhone pairing if
  we want iOS to remember Car Thing as an audio-capable device.
- Current release recipe uses `AudioSink + AVRCP Target`, CoD loudspeaker
  `0x240414`, one visible name from `identity_service.visible_name()`, and no
  separate classic name.

## Fosi Standalone Test

Use the standalone tools first. Do not run this through the full GUI runtime.

Preconditions:

- Runtime stopped.
- Fosi power-cycled if a previous test failed.
- One clean attempt only. Retry storms leave stale ACL/AVDTP state.
- Use `hci-socket:0`, not `serial:/dev/ttyS1`, because `btattach` already owns
  the UART and exposes `hci0`.

Stop the runtime:

```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  ps w | awk "/carthing_runtime.py/ && !/awk/ {print \$1}" | while read p; do kill "$p" 2>/dev/null || true; done
  rm -f /run/carthing/media-remote-supervisor.pid
'
```

Copy the current tools to the device:

```sh
cd (local repo root)
COPYFILE_DISABLE=1 tar --no-xattrs -cf - \
  tools/fosi-a2dp-standalone-test.py \
  tools/fosi-pseudo-source.py |
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  tar -xf - -C /tmp
'
```

Run the pure handshake test:

```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  python3 /tmp/tools/fosi-a2dp-standalone-test.py
'
```

Success criteria:

- `encrypted=True` or `A2DP receiver link ENCRYPTED ok`.
- SDP version lookup succeeds or does not block AVDTP.
- remote endpoints are discovered.
- compatible sink is selected.
- `A2DP_STREAMING_OK` or `A2DP_SPEAKER_STREAM_STARTED`.

Failure meanings:

- `HCI_PIN_OR_KEY_MISSING [0x6]`: there is no valid classic link-key; JSON
  trusted row is not enough.
- `CONNECTION_REFUSED_SECURITY_BLOCK`: Fosi refused AVDTP because the link is
  not encrypted.
- `HCI_CONNECTION_ALREADY_EXISTS [0xB]`: stale ACL on Car Thing side. Reset
  `hci0` by restarting `btattach` or rebooting the device.
- `CONNECTION_REFUSED_NO_RESOURCES`, silent discovery timeout, or `reason=0x13`:
  stale AVDTP/resource state on Fosi. Power-cycle Fosi.
- `HCI_PAGE_TIMEOUT_ERROR`: Fosi is off, occupied, not reachable, or not in a
  state where it accepts the page.

## Audible Fosi Test

Generate an SBC tone on the Mac if `/run/tone.sbc` is missing on the device:

```sh
ffmpeg -f lavfi -i "sine=frequency=880:duration=20:sample_rate=44100" \
  -ac 2 -c:a sbc -f sbc /tmp/tone.sbc
scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no \
  /tmp/tone.sbc root@172.16.42.77:/run/tone.sbc
```

Then run:

```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  python3 /tmp/tools/fosi-pseudo-source.py
'
```

Success criteria:

- `A2DP_STREAMING_OK`.
- The script sends RTP packets for about 15 seconds.
- Fosi audibly plays the tone.
- The script exits with `CLEAN EXIT (Fosi released)`.

## Returning To Runtime

After tests, restart the normal runtime:

```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  rm -f /run/carthing/media-remote-supervisor.pid
  setsid sh /etc/init.d/S50-carthing-remote >/dev/null 2>&1 &
'
```

Check:

```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@172.16.42.77 '
  tail -n 160 /run/carthing/carthing-remote.log |
  grep -Ei "AMS: ready|A2DP|Fosi|connected:|STREAM|sent_to_speaker|link-key|Visibility"
'
```

## What Must Not Be Done

- Do not add Fosi as trusted unless strict classic pairing/encryption succeeds.
- Do not remove Fosi's `classic_avrcp` endpoint. It is a control-capable device.
- Do not use retry storms during pairing. One clean attempt, clean teardown.
- Do not use a manual JSON row as a substitute for physical bond evidence.
- Do not split iPhone into separate BLE and classic user-visible devices.
