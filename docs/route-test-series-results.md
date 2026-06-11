# Route Test Series Results

Append-only log for live route tests. Keep entries chronological.

## 2026-06-11 — Codex session start

Context:
- Started from `docs/RUNBOOK-NEXT.md`.
- Device reachable over SSH as `carthing`; visible identity: `Car Thing (SN: QN19)`.
- Runtime is up: `python3 /usr/lib/carthing/carthing_runtime.py`.
- Baseline log has `GUI active`, `AMS: ready`, Fosi receiver setup, and `grep -c Traceback` returned `0`.
- Known output under test: Fosi Audio ZD3, address `C4:A9:B8:70:2F:E5`.
- Recent route output transitions in log: Fosi selected, then Play Now selected.

Planned first live sequence:
1. Use existing Fosi route as control.
2. Pair a second Bluetooth speaker through `[ADD]`.
3. Select second speaker as output and apply `[LNK]`.
4. Switch outputs under a playing iPhone source and capture whether receiver handoff works.

### Maedhawk BT Cable pairing

Observed before fix:
- `[ADD]` scan found `Maedhawk BT Cable`, address `41:42:9C:A0:BD:14`, `audio=True`.
- Classic link key was written to `keys.json`.
- A2DP endpoint discovery succeeded and `A2DP stream opened+held after pairing` appeared.
- GUI did not show the device because `state.json` did not get a speaker trusted-card.

Fix applied:
- `overlay/usr/lib/carthing/a2dp_bridge.py` now preserves the already-proven speaker role during SDP enrichment: for an audio pairable candidate, enrichment adds `audio_sink` and `110b` instead of allowing incomplete SDP UUIDs to downgrade the device.
- Deployed with `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`.
- Smoke checks: local `py_compile`, local import with vendored Bumble in `PYTHONPATH`, runtime `GUI active`, `AMS: ready`, `Traceback=0`.

Observed after fix:
- Repeat `[ADD]` produced `device card enriched: 41:42:9C:A0:BD:14 -> ['0003', '0100', '1002', '110b', '111e', '1203', 'audio_sink']`.
- `state.json` now contains `speaker Maedhawk BT Cable 41:42:9C:A0:BD:14 ['audio_output', 'control_input', 'transport_control', 'volume_control']`.
- Next step: verify GUI shows Cable as output, then select it and apply `[LNK]`.

### Maedhawk selected but RTP fell back to Fosi

Owner observation:
- Selecting `Maedhawk BT Cable` as output made the GUI route look active, but no audio came out.
- After roughly a minute, audio appeared on another output, in this run Fosi.

Log evidence:
- Maedhawk receiver attempts repeatedly failed with `L2CAP/CONNECTION_REFUSED_NO_RESOURCES_AVAILABLE [0x4]`.
- During that failure window RTP showed `sent_to_speaker=False` and dropped packets increased.
- Later standby connected Fosi and opened its receiver; RTP then changed to `sent_to_speaker=True`, matching the owner observation that audio moved to Fosi.

Diagnosis:
- `handle_classic_connection()` let any trusted speaker classic connection call `request_receiver_for_active_source(peer_address)`.
- With multiple speakers, a standby reconnect from Fosi could steal the active receiver even though the selected/default route output was Maedhawk.
- Auto retries also ignored `_speaker_backoff` in the receiver request entrypoint, so `0x4` failures could storm instead of waiting.

Fix applied:
- Active source routing now only opens receiver for the selected/default speaker; non-selected trusted speaker classic connections are logged and ignored for the active route.
- `request_receiver_connection()` now honors `_speaker_backoff` unless called with `force=True`.
- Explicit GUI route selection calls `request_receiver_connection(key, force=True)`, so manual `[LNK]`/selection remains an intentional retry.
- Deployed `a2dp_bridge.py` and `carthing_runtime.py` with `tools/deploy ... --restart`; post-restart baseline: `GUI active`, `AMS: ready`, `Traceback=0`.

Next live check:
- Select `Maedhawk BT Cable`, apply `[LNK]`, and confirm whether failure stays silent/on Maedhawk instead of falling through to Fosi.
- If Maedhawk still returns `0x4`, debug that receiver independently; the route-steal bug should no longer mask it by moving audio to Fosi.

### Follow-up: standby still could open non-selected receiver before source stream

Observed after the first guardrail:
- A previous log window still showed Fosi becoming receiver after Maedhawk failed.
- Cause: Fosi standby could open AVDTP before `source_stream_active=True`; after the iPhone stream started, RTP used the already-open Fosi receiver.

Additional fix:
- `ensure_trusted_speakers_connected()` now treats `default_speaker_address()` as the only allowed media receiver target while `a2dp_bridge` still has one global `receiver_*` slot.
- Non-default trusted speakers are not opened as AVDTP standby receivers. This is a compatibility guardrail until real per-device connector state exists.

Verification:
- Deployed `a2dp_bridge.py` with `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`.
- Baseline after restart: `GUI active`, `AMS: ready`, `Traceback=0`.
- `state.json`: `Maedhawk BT Cable` is default speaker; Fosi is trusted but not default.
- A 30-second live-tail after restart showed no new Fosi standby/receiver events.

Next live check:
- From Play Now, select `Maedhawk BT Cable`, apply `[LNK]`, play iPhone audio.
- Expected guardrail result: if Maedhawk fails, RTP should remain dropped/silent and Fosi should not become `sent_to_speaker=True` by stealing the global receiver.

### Correction: non-default standby suppression broke Fosi

Owner correction:
- Suppressing non-default AVDTP standby is not acceptable.
- Fosi uses held AVDTP standby to leave pairing mode; without it Fosi falls back into pairing/discoverable behavior.

Action taken:
- Reverted the `ensure_trusted_speakers_connected()` filter that allowed standby only for `default_speaker_address()`.
- Redeployed `a2dp_bridge.py` with `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`.

Verification:
- Baseline after restart: `GUI active`, `AMS: ready`, `Traceback=0`.
- Fosi receiver path came back:
  `A2DP receiver sink selected: address=C4:A9:B8:70:2F:E5 codec=AAC seid=3`
  followed by `A2DP_SPEAKER_STREAM_STARTED codec=AAC seid=3`.

Current status:
- Fosi golden standby behavior restored.
- Remaining deployed `a2dp_bridge.py` changes are:
  - preserve speaker role during Cable enrichment;
  - receiver request backoff unless `force=True`;
  - active-source classic connection can only request receiver for the selected/default speaker.
- The deeper multi-speaker route-steal problem is not solved by suppressing standby; it needs real per-device connector state or a route transition that does not break Fosi standby.

### Per-speaker connector implementation deployed

Owner direction:
- Stop handling future speakers with one-off Fosi/Maedhawk exceptions.
- Each trusted output needs its own connector state because the next device may require a
  different standby/session environment.

Implementation:
- Added `SpeakerConnector` map in `a2dp_bridge.py`.
- Receiver AVDTP protocol/source/stream/rtp_channel/last_error now live per speaker address.
- Legacy `receiver_*` fields are retained as a compatibility view of the selected connector.
- RTP forwarding now targets only the connector for `default_speaker_address()`.
- Speaker runtime connected state now uses `set_speaker_connected(address, True)`, not
  `set_connected_speaker()`, so multiple standby connectors can coexist.

Verification:
- Local `py_compile` and import passed.
- Deployed twice with `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`; second deploy
  included the connected-state correction.
- Post-deploy baseline:
  - `GUI active`
  - `AMS: ready`
  - `Traceback=0`
- Fresh log window after `2026-06-11 20:27:03`:
  - Fosi: `A2DP_SPEAKER_STREAM_STARTED codec=AAC seid=3`
  - Maedhawk: `A2DP_SPEAKER_STREAM_STARTED codec=SBC seid=1`
  - no fresh `A2DP receiver disconnected`
  - no fresh `A2DP receiver connect failed`

Manual test still needed:
- Start iPhone playback with Maedhawk selected/default.
- Expected: RTP should not fall through to Fosi merely because Fosi standby is alive.

### Live Maedhawk route test: GUI freeze caused by unhandled closed RTP channel

Owner observation:
- Route switched on, but no audio came out.
- GUI then appeared frozen.

Evidence:
- Before the fault, route selection was correct:
  `route output selected: 41:42:9C:A0:BD:14`
- Maedhawk receiver was considered ready:
  `A2DP receiver already ready: 41:42:9C:A0:BD:14`
- RTP initially tried to go to selected speaker:
  `A2DP_BRIDGE_RTP forwarded=1..9 dropped=0 sent_to_speaker=True`
- Then Bumble packet path flooded Tracebacks:
  `bumble.core.InvalidStateError: channel not open` from `forward_packet() -> channel.send_pdu(payload)`.

Fix:
- `forward_packet()` catches send failures, drops the packet, clears the dead selected connector
  media stream/channel, and schedules reconnect instead of raising inside Bumble callbacks.
- Follow-up correction clears `source/stream` as well as `rtp_channel`, so retry rebuilds the
  stream instead of resuming a stale closed channel.

Verification:
- Local compile/import passed.
- Deployed with `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`.
- Fresh post-hotfix window after `2026-06-11 20:36:00`:
  - `GUI active`
  - `AMS: ready`
  - Fosi AAC standby stream started.
  - Maedhawk SBC standby stream started.
  - no fresh `Traceback` / `Exception in on_packet`.

Current status:
- GUI freeze hotfixed.
- Audio on Maedhawk is still not proven. Evidence now points to Maedhawk media channel closing
  shortly after RTP starts, not to Fosi route stealing.

### Codec mismatch confirmed: iPhone AAC source vs Maedhawk SBC receiver

Owner observation:
- iPhone sees Car Thing as the selected audio output and keeps sending music.
- Maedhawk is selected/connected as route output, but no audio is heard.

Evidence:
- iPhone source config:
  `A2DP_SOURCE_SET_CONFIGURATION codec=AAC`
- Maedhawk receiver config:
  `A2DP receiver sink selected: address=41:42:9C:A0:BD:14 codec=SBC seid=1`

Conclusion:
- The bridge is forwarding encoded RTP without transcoding.
- AAC input can work with Fosi because Fosi accepts AAC.
- Maedhawk is SBC-only in this test; AAC RTP into an SBC stream explains "route active,
  iPhone sending, no audio".

Fix deployed:
- Track source codec.
- Offer AAC to iPhone only when the selected receiver route is not SBC-only.
- For Maedhawk/SBC route, advertise `SBC-only route-compatible`.
- Drop codec-mismatched RTP and close source for renegotiation instead of feeding the
  wrong codec into the selected speaker.
- `carthing_runtime._apply_route_output()` triggers source codec compatibility check after
  selecting an output.

Expected next-test markers:
- `A2DP source endpoint profile=SBC-only route-compatible`
- `A2DP_SOURCE_SET_CONFIGURATION codec=SBC`
- `A2DP_SOURCE_START codec=SBC`
- `A2DP_BRIDGE_RTP ... sent_to_speaker=True`

### Regression: Fosi GUI selection did not update bridge default

Owner observation:
- Fosi selected in GUI, but Maedhawk still activated/received transport behavior.

Evidence:
- `state.json` showed Fosi as `route_output=True` while Maedhawk remained `default=True`.
- Transport code uses `bridge.state.default_speaker_address()` for forwarding and codec decisions.

Fix:
- `carthing_runtime._apply_route_output()` now updates both GUI state and bridge state default speaker.
- It saves trusted state after default mutation, not only before route application.

Expected next-test marker:
- After selecting Fosi, transport logs should reference `C4:A9:B8:70:2F:E5`, not Maedhawk.
