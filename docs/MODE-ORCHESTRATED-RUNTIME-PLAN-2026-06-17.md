# Mode-Orchestrated Runtime Plan — QN19 — 2026-06-17

Status: proposed workstream after `qn19-early-gui-2026-06-17`.

This is the larger task that should group the next related changes. The goal is
not another isolated boot tweak; the goal is to make the selected product mode
own runtime resources.

## Product Modes

| Mode | Product meaning | Allowed baseline work | Must stay off |
|------|-----------------|-----------------------|---------------|
| `playnow` | Default. Car Thing is a fast media/control surface for the iPhone. | DRM/GUI, input, BLE pairing/reconnect, AMS/ANCS/CTS/metadata/control, notifications, runtime state publish. | speaker standby loop, receiver paging, A2DP source routing to speakers, route patchbay activation, speaker scans unless user starts pairing. |
| `commutator` | Full audio switchboard/router. | Everything in Play Now plus explicit route graph, selected speaker standby/connection, A2DP sink/source, AVRCP backchannel, codec/relay path. | hidden routes not requested by the active session. |
| `reserved` | Future USB-oriented slot. | For now behaves like Play Now. | Bluetooth switchboard behavior unless the future USB session explicitly asks for it. |

## Current Code Facts

- `operation_mode.py` already defines `PLAYNOW`, `COMMUTATOR`, `RESERVED`, and
  `DEFAULT = PLAYNOW`.
- `AppState` still initializes `operation_mode` as `"commutator"` before runtime
  loads settings. This should be aligned with `operation_mode.DEFAULT`.
- `TransferService.start()` always installs SDP records and starts the AVDTP
  listener, then only gates the speaker standby loop by `operation_mode`.
- `carthing_runtime._on_set_mode()` can start or stop the standby loop live, but
  mode selection is not yet a central session/resource owner.
- `_on_session_select()` is a no-op, while route activation, Play Now selection,
  transfer state, and operation mode live in separate partial mechanisms.

## Desired Contract

The runtime should have one explicit mode owner:

```text
boot
  -> early GUI home shell
  -> load settings.operation_mode
  -> apply mode plan
  -> start only the adapters required by that mode
  -> publish mode/resource state
```

Mode application must be deterministic:

```text
stop resources forbidden by target mode
preserve resources allowed to stay idle
start resources required by target mode
publish model/app_state
record BOOT_PROFILE/RUNTIME_PROFILE milestones
```

## Implementation Slices

1. **Mode contract and tests**
   - Add a small mode planner/contract module or extend `operation_mode.py` with
     explicit resource flags.
   - Define resources such as `gui`, `ble_control`, `notifications`,
     `speaker_standby`, `a2dp_listener`, `route_patchbay`, `speaker_scan`,
     `usb_profile`.
   - Add tests proving `playnow` does not enable commutator-only resources.

2. **Default alignment**
   - Make `AppState.operation_mode` default to `operation_mode.DEFAULT`.
   - Ensure settings load cannot briefly show or publish `commutator` when the
     product default is Play Now.

3. **Runtime mode owner**
   - Replace scattered mode effects with one `apply_operation_mode(mode)` path.
   - Mode switching should update `AppState`, `RuntimeModel`, transfer bridge,
     standby tasks, route plan, and published JSON in one place.

4. **Play Now minimal boot**
   - In `playnow`, avoid starting commutator-only background loops.
   - Decide by proof whether AVDTP listener/SDP setup is still needed at boot or
     should be lazy-started only when the user activates a route.
   - Keep BLE AMS/ANCS/CTS and UI metadata/control path fast.

5. **Commutator activation**
   - Make selected route activation transition from Play Now into the commutator
     resource set intentionally.
   - Start only the selected speaker path first; do not page every trusted output.
   - Keep route activation serialized through the existing HCI gate.

6. **Reserved/USB preparation**
   - Keep `reserved` behavior equivalent to Play Now until USB routing exists.
   - Add a documented resource slot for future USB profile/session ownership.

7. **Proof and bake**
   - Add mode-specific `BOOT_PROFILE`/runtime log lines:
     `mode.loaded`, `mode.applied`, `mode.resources`.
   - Extend `check-bake-readiness.sh` with mode contract checks.
   - Live proof on QN19 for:
     - cold boot Play Now;
     - switch Play Now -> Коммутатор -> Play Now;
     - selected route activation/deactivation;
     - rootfs remains readonly and state writes remain controlled.

## Acceptance Criteria

- Cold boot default is Play Now in settings, GUI, runtime JSON, and logs.
- In Play Now, no speaker standby loop or receiver paging runs unless pairing or
  route activation explicitly requests it.
- Коммутатор starts only through explicit mode/route action and tears down cleanly.
- Резерв does not accidentally start Bluetooth switchboard work.
- `scripts/check-bake-readiness.sh` catches regressions in the mode contract.
- The final state is baked into `image/rootfs.img`, verified on QN19, committed,
  and tagged as the next product baseline.
