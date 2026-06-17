# Route-Load Proof — QN19 — 2026-06-18

Scope: proof for quiet Play Now, manual/event-driven Коммутатор, and iPhone
stickiness while Fosi Audio ZD3 is connected for a full route test.

## Implemented

- Added `tools/route-load-proof.sh` host proof script.
- Play Now now tears down completed/done standby tasks and refreshes
  `actual_*` resource state before every runtime JSON publish.
- Коммутатор standby is route-scoped by default: only the selected output is
  paged/held. Lab all-speaker soak remains opt-in with
  `CARTHING_STANDBY_ALL_SPEAKERS=1`.
- Periodic `LinkManager.start()` polling is disabled. The runtime does one boot
  tick only; trusted-device status should be refreshed by explicit user actions.
- `speaker_scan` is no longer a mode-owned background resource. Scans remain
  manual/event-driven through rescan, pairing, selection, or activation flows.
- Returning to Play Now releases the external speaker Classic ACL without
  forgetting pairing keys or trusted-device rows.

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

RUNTIME TREE SHA OK: 856683dc1506cab30070c0229ca44aef1330ed48
BAKE READINESS: OK (local userspace gates)
```

## Bake

Local bake completed after live proof:

```text
bundle: flash-bake-unified-stable-20260618-013904
bootfs.bin sha256: 6e99a75c57e38acab5be5b818f559132a4b7a167e7ccfa80e4e3ce1aedd7df3e
rootfs.img sha256: f5b6b1994c45174fef66d8947b0dd49679ebebe93bf70f5d7e545a512cbfb4ac
env.txt sha256: 622490729632aeb3eff2fffe89da6fc13b800f51eda77791e27d89225363fb69
meta.json sha256: 121f3ea3327d5a6ae2575d54c5d8e2cf1cd3a1b1d48a3c5760fdff3017b1b56c
```

This bundle has not been flashed in full.

## Live QN19 Proof

Final artifact:

```text
artifacts/route-load-20260618-013706/proof.json
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
  Maedhawk connected=false standby=false status=offline
  actual_standby_loop=true actual_receiver_stream=true actual_speaker_scan=false

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

operation mode applied: mode=commutator ... speaker_scan=False actual_standby_loop=True
A2DP speaker standby connect: C4:A9:B8:70:2F:E5

A2DP speaker classic ACL disconnected for Play Now: C4:A9:B8:70:2F:E5
operation mode applied: mode=playnow ... actual_standby_loop=False actual_receiver_stream=False actual_speaker_scan=False
A2DP source classic ACL disconnected (back to BLE-only)
```

No new Maedhawk standby/page attempt appeared in the final proof window.

## Remaining

- macOS as audio input is still unproven. It needs a separate controlled pairing
  and route proof to discover the exact A2DP/AVRCP/SDP profile macOS accepts.
- AVDTP/SDP listener is still started at boot as a transitional compatibility
  surface. Lazy listener startup should be researched separately because it can
  affect iPhone stickiness and pairing behavior.
