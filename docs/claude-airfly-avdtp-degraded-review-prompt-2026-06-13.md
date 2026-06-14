# Claude Prompt: AirFly Pro AVDTP degraded output review

You are reviewing a local Python codebase for a Spotify Car Thing Bluetooth routing project.

Repository root:

```text
(local repo root)
```

Do not propose BlueZ, bluetoothctl, sdptool, RFCOMM/PAN, or Linux desktop Bluetooth tooling. This runtime is Bumble-based and runs on the Car Thing target.

## Current live state after latest Codex patch

The runtime has a unified trusted-device registry/card model. Current route is Play Now / CarThing:

```text
route_output=carthing
active_route_output=carthing
```

Fosi and Maedhawk both recover standby after runtime restart:

```text
Fosi Audio ZD3      standby=true codec=AAC
Maedhawk BT Cable   standby=true codec=SBC
```

AirFly Pro exists as its own output card, but AVDTP profile collection is degraded:

```text
AirFly Pro 20:23:00:00:46:8F
status=backoff
last_error=disconnected 0x13
missing_capability:avdtp_profile
enrollment_evidence.avdtp_probe.status=failed
enrollment_evidence.avdtp_probe.error="avdtp discover timeout"
```

Important recent fix in `overlay/usr/lib/carthing/a2dp_bridge.py`:

- rejected incoming AVDTP source channels from trusted speakers are now explicitly closed instead of being left open;
- AVDTP discover timeout now persists `avdtp_probe` and `missing_capabilities=["avdtp_profile"]` into the device card;
- `on_speaker_disconnected()` no longer clears an active receiver backoff. This stopped AirFly from hammering every ~12-25 seconds after a timeout.

Observed live AirFly sequence:

```text
A2DP speaker standby connect: 20:23:00:00:46:8F
A2DP_SPEAKER_STANDBY_CONNECTED 20:23:00:00:46:8F
A2DP receiver link ENCRYPTED ok: 20:23:00:00:46:8F
A2DP receiver AVDTP connect: 20:23:00:00:46:8F version=(1, 3)
A2DP receiver discover endpoints: 20:23:00:00:46:8F
A2DP receiver discover timeout: address=20:23:00:00:46:8F version=(1, 3)
device card AVDTP failure persisted: 20:23:00:00:46:8F error=avdtp discover timeout
A2DP receiver connect failed: avdtp discover timeout (retry in 300s)
A2DP speaker disconnect kept receiver backoff: 20:23:00:00:46:8F remaining=298s reason=19
```

## Files to inspect first

```text
overlay/usr/lib/carthing/a2dp_bridge.py
overlay/usr/lib/carthing/app_state.py
overlay/usr/lib/carthing/enrollment_manager.py
overlay/usr/lib/carthing/route_graph.py
scripts/smoke-route-graph.py
scripts/check-route-architecture.py
```

## Review task

Do a code review and diagnostic design pass, not a rewrite.

Findings format:

- Severity: P0/P1/P2/P3.
- File/function.
- Exact behavioral risk.
- Why it explains AirFly or could regress other outputs.
- Minimal recommended fix.
- Test or live verification needed.

Prioritize:

1. Bugs that can still cause AirFly retry/backoff to leak into Fosi/Maedhawk standby.
2. Bugs in AVDTP version lookup, protocol connect, endpoint discovery, or close/teardown that could explain AirFly discover timeout.
3. Missing passport evidence fields needed to distinguish "device is not an A2DP sink" vs "device disconnected before discovery" vs "we used the wrong mode".
4. Whether AirFly-like RX/TX devices need an explicit mode/routing constraint in the card before being treated as normal output.
5. Minimal diagnostic logging that would make the next live test conclusive without spamming the runtime.

Constraints:

- Keep the card-index architecture.
- Keep per-device runtime/standby cells.
- Do not reintroduce any speaker `default`; `default` means only Play Now / CarThing.
- Do not make selecting an output in GUI activate the route; LNK is the confirmation boundary.
- Do not disable standby for all devices because AirFly is degraded.
