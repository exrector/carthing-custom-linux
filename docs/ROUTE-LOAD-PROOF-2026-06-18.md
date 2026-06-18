# Route-Load Proof — QN19 — 2026-06-18

Scope: proof for quiet Play Now, manual/event-driven Коммутатор, and iPhone
stickiness while Fosi Audio ZD3 is connected for a full route test.

## Implemented

- Added `tools/route-load-proof.sh` host proof script.
- Play Now now tears down completed/done standby tasks and refreshes
  `actual_*` resource state before every runtime JSON publish.
- Коммутатор standby is snapshot-scoped by default: entering Коммутатор runs one
  explicit trusted-output scan, then holds the trusted outputs that were found
  online. Manual output selection can add its target to the snapshot. Lab
  all-speaker soak remains opt-in with `CARTHING_STANDBY_ALL_SPEAKERS=1`.
- Periodic `LinkManager.start()` polling is disabled. The runtime does one boot
  tick only; trusted-device status should be refreshed by explicit user actions.
- `speaker_scan` is no longer a mode-owned background resource. Scans remain
  manual/event-driven through rescan, pairing, selection, or activation flows.
- Returning to Play Now releases the external speaker Classic ACL without
  forgetting pairing keys or trusted-device rows.
- Play Now teardown now clears all known trusted output footprints, not only
  volatile `SpeakerRuntime` cells, so stale GUI `connected` flags cannot survive
  a mode return.
- Route-view terminal status now shows product mode/action (`MODE: PLAY NOW`,
  `MODE: COMM SCAN`, `MODE: COMM HOLD N`, `MODE: COMM LINK WAIT/PLAY`) instead
  of the unhelpful `ROUTE: -`.
- In Play Now, external output rows are visually dimmed as inactive. Normal
  output coloring returns only in Коммутатор.

## Guardrails Preserved

- iPhone sticky BLE/metadata path stays active in Play Now:
  `ble_control=true`, notifications stay enabled, `orch.kick_reconnect()` remains
  scheduled, AMS/ANCS/CTS are not stopped by speaker teardown.
- The external speaker teardown touches only speaker runtime/ACL/AVDTP state.
  It does not delete keys, trusted rows, or iPhone BLE state.

## Local Gates

```text
python3 -m py_compile overlay/usr/lib/carthing/a2dp_bridge.py \
  overlay/usr/lib/carthing/transfer_service.py \
  overlay/usr/lib/carthing/carthing_runtime.py \
  overlay/usr/lib/carthing/operation_mode.py \
  scripts/check-operation-mode-contract.py
bash -n tools/route-load-proof.sh
./scripts/check-bake-readiness.sh
git diff --check

RUNTIME TREE SHA OK: 1dd0d1d9ab0e2cdad4662c665eb2caeee3487b61
BAKE READINESS: OK (local userspace gates)
```

## Bake

Local bake completed after live proof:

```text
bundle: flash-bake-unified-stable-20260618-015815
bootfs.bin sha256: 6e99a75c57e38acab5be5b818f559132a4b7a167e7ccfa80e4e3ce1aedd7df3e
rootfs.img sha256: 174ad69defe7a2edf4ed857ef61cf513e90b81766c2769109de2268fae2ed589
env.txt sha256: 622490729632aeb3eff2fffe89da6fc13b800f51eda77791e27d89225363fb69
meta.json sha256: 121f3ea3327d5a6ae2575d54c5d8e2cf1cd3a1b1d48a3c5760fdff3017b1b56c
```

This bundle has not been flashed in full.

## Live QN19 Proof

Final artifact:

```text
artifacts/route-load-20260618-015708/proof.json
```

Summary from the final proof:

```text
before:
  mode=playnow governor=schedutil source_connected=true source_peer=10:A2:D3:83:82:50/P
  Fosi connected=false standby=false; Maedhawk connected=false standby=false
  actual_standby_loop=false actual_receiver_stream=false actual_speaker_scan=false

commutator-hold:
  mode=commutator governor=performance source_connected=true source_peer=10:A2:D3:83:82:50/P
  Fosi connected=true standby=true status=active
  Maedhawk connected=true standby=true status=standby
  actual_standby_loop=true actual_receiver_stream=true actual_source_stream=true packets_forwarded=23

after:
  mode=playnow governor=schedutil source_connected=true source_peer=10:A2:D3:83:82:50/P
  Fosi connected=false standby=false status=offline
  Maedhawk connected=false standby=false status=offline
  actual_standby_loop=false actual_receiver_stream=false actual_speaker_scan=false
```

Focused live log evidence:

```text
link manager periodic polling disabled; boot tick only
AMS: ready
trusted sources synced after AMS: 10:A2:D3:83:82:50

A2DP trusted speaker seen: 41:42:9C:A0:BD:14
A2DP trusted speaker seen: C4:A9:B8:70:2F:E5
A2DP standby snapshot refreshed: count=2 addresses=41:42:9C:A0:BD:14,C4:A9:B8:70:2F:E5
operation mode applied: mode=commutator ... actual_standby_loop=True actual_receiver_connecting=True
A2DP speaker standby connect: C4:A9:B8:70:2F:E5
A2DP speaker standby connect: 41:42:9C:A0:BD:14

A2DP speaker classic ACL disconnected for Play Now: 41:42:9C:A0:BD:14
A2DP speaker classic ACL disconnected for Play Now: C4:A9:B8:70:2F:E5
operation mode applied: mode=playnow ... actual_standby_loop=False actual_receiver_stream=False actual_speaker_scan=False
A2DP source classic ACL disconnected (back to BLE-only)
```

No constant background polling appeared in the final proof window. Maedhawk was
held because it was found by the explicit Коммутатор entry snapshot, then it was
released with Fosi on return to Play Now.

## Remaining

- macOS as audio input is still unproven. It needs a separate controlled pairing
  and route proof to discover the exact A2DP/AVRCP/SDP profile macOS accepts.
- AVDTP/SDP listener is still started at boot as a transitional compatibility
  surface. Lazy listener startup should be researched separately because it can
  affect iPhone stickiness and pairing behavior.

## Follow-up 2026-06-18 10:27 — Source-First Play Now Teardown

Owner correction: "do not just tear down output ACLs; tell the source first that
we are going to end the route." Implemented in `TransferService.apply_operation_mode()`:
Play Now transitions now call `bridge.disconnect_source()` before stopping
standby/receiver streams and releasing external speaker ACLs.

Why: `disconnect_source()` already performs the polite iPhone path: close the
A2DP source stream, close AVDTP signaling, then release Classic ACL while leaving
BLE/AMS/ANCS/CTS intact. Running that before output teardown prevents the source
from continuing to send RTP into an output that is already disappearing.

Live check after deploy:

```text
transfer_service.py deployed with restart
operation_mode before/after remains playnow
source_connected=true source_peer=10:A2:D3:83:82:50/P
10:26:38 A2DP source classic ACL disconnected (back to BLE-only)
10:26:38 transfer mode applied: mode=playnow ...
```

Limit of that live check: Fosi was unavailable/backoff and no source RTP stream
was opened, so the active-stream log lines (`A2DP source stream closed gracefully`,
`A2DP source AVDTP signaling closed gracefully`) were not re-exercised in this
specific proof. The code path is the same `disconnect_source()` path already
used for iPhone graceful return; a full audio proof should be repeated with Fosi
online and playback active.

## Follow-up 2026-06-18 10:35 — Play Now Rejects Incoming Outputs

Owner-observed failure: Fosi Audio ZD3 was powered on while the GUI showed Play
Now, and it still connected to CarThing. The earlier fix stopped our outgoing
standby/receiver loops, but it did not reject a bonded/trusted speaker that
initiated Classic/AVCTP/AVDTP from the outside.

Implemented in `a2dp_bridge.py`:

- Added `_speaker_allowed_in_current_mode()`, a role-scoped gate for trusted
  output devices.
- In Play Now, trusted speaker-owned Classic ACL, AVCTP and AVDTP surfaces are
  rejected/disconnected immediately.
- In Коммутатор, incoming speaker surfaces are accepted only for the entry
  snapshot, the selected route output, or explicit lab mode
  `CARTHING_STANDBY_ALL_SPEAKERS=1`.
- Trusted source/iPhone handling is not gated by this speaker rule, preserving
  BLE/AMS/ANCS/CTS stickiness.

Live check after deploy:

```text
tools/deploy usr/lib/carthing/a2dp_bridge.py --restart

runtime up in Play Now
iPhone source connected=true peer=10:A2:D3:83:82:50/P
AMS ready, ANCS ready, CTS ready

after 70s with Fosi powered on:
operation_mode=playnow
mode_resources.actual_standby_loop=false
mode_resources.actual_receiver_stream=false
mode_resources.actual_receiver_connecting=false
Fosi Audio ZD3 connected=false standby=false connecting=false status=offline
Maedhawk BT Cable connected=false standby=false connecting=false status=offline
```

The same log window records the pre-fix failure at 10:31 (`Classic BT
connection`, `AVCTP incoming`, `AVRCP speaker backchannel armed` for Fosi), and
no equivalent Fosi footprint after the patched 10:35 restart. A direct rejection
line will appear only if the speaker initiates a fresh incoming connection; the
state proof already confirms that Play Now no longer keeps or reports an
external output link while Fosi is powered.
