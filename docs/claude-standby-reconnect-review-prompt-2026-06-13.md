# Claude Prompt: CarThing standby/reconnect and passport review

You are reviewing a local Python codebase for a Spotify Car Thing Bluetooth routing project.

Repository root:

```text
(local repo root)
```

Do not use BlueZ, bluetoothctl, sdptool, RFCOMM/PAN, or Linux desktop Bluetooth tooling as proposed fixes. This project uses the in-repo Bumble-based runtime.

## Current observed live state

After a reboot, SSH access works through macOS USB/NCM:

```sh
scripts/bring-up-device1-normal-boot-macos.sh --bsd en14
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@172.16.42.77
```

The persistent device registry contains:

- iPhone `10:A2:D3:83:82:50`: input/source, AMS/ANCS/HID/A2DP sink ready.
- Fosi `C4:A9:B8:70:2F:E5`: output, AVDTP/AVRCP ready, codecs `AAC`, `SBC`, vendor codecs.
- Maedhawk `41:42:9C:A0:BD:14`: output, AVDTP/AVRCP ready, codec `SBC`.
- AirFly Pro `20:23:00:00:46:8F`: output card exists, `classic_sdp_ready`, but no persisted `avdtp_profile.supported_codecs` yet.

The route is correctly back to Play Now / CarThing:

```text
route_output carthing
active_route_output carthing
```

Recent runtime symptom after reboot: all trusted outputs enter standby/backoff attempts with `PAGE_TIMEOUT_ERROR`, while iPhone source remains connected. AirFly can get an encrypted ACL sometimes but fails or disconnects before AVDTP codec discovery completes.

## Files to inspect first

```text
overlay/usr/lib/carthing/a2dp_bridge.py
overlay/usr/lib/carthing/app_state.py
overlay/usr/lib/carthing/transfer_service.py
overlay/usr/lib/carthing/carthing_runtime.py
overlay/usr/lib/carthing/intents.py
overlay/usr/lib/carthing/screens.py
scripts/smoke-route-graph.py
scripts/check-route-architecture.py
```

Focus areas:

1. `SpeakerRuntime`, `_speaker_runtimes`, `speaker_statuses()`.
2. `start_standby_loop()`, `speaker_standby_loop()`, `ensure_trusted_speakers_connected()`.
3. `ensure_speaker_connection()`, `setup_receiver()`, AVDTP discovery and backoff.
4. `pair_speaker()` and how enrollment/passport data is persisted.
5. Route selection boundaries: adding/pairing a speaker must not activate the route. Only explicit route activation via LNK should change active output.
6. Delete/remove behavior: removing a trusted output must clear runtime shadows, link keys, candidates, route flags, and standby ownership.

## Architecture constraints

- One registry/card per trusted device. A device may be input, output, or both.
- Each output card owns its own standby/runtime cell. No single global default speaker connector.
- `default` means only Play Now / CarThing route. Do not reintroduce a default output device.
- GUI selects desired route; LNK confirms activation. Simple tapping a route/output must not activate audio.
- `OUT+` enrollment creates or updates a card and may open standby, but must not change the active route.
- Standby is per output card: all trusted online outputs should be held/retried independently, with bounded backoff and clear state.
- Passport/enrollment must record evidence: Classic CoD/SDP, AVDTP endpoints/codecs, AVRCP events, BLE advertisement/GATT evidence when available, and unknown/degraded fields when unavailable.

## Review task

Do a code review, not a rewrite. Produce findings with:

- Severity: P0/P1/P2/P3.
- File and function.
- Exact behavioral risk.
- Why it can explain current live symptoms or future regressions.
- Minimal recommended fix.
- Test or live verification needed.

Prioritize:

1. Bugs that can cause standby attempts to serialize badly, starve other outputs, or keep all outputs in backoff after reboot.
2. Bugs that prevent AVDTP profile collection for AirFly-like devices.
3. Bugs where route selection state can leak into card persistence or enrollment.
4. Bugs where UI shows success but transport/passport is degraded without a clear status.
5. Missing tests for the above invariants.

Do not propose replacing the architecture. Do not propose BlueZ. Keep recommendations scoped to this codebase.
