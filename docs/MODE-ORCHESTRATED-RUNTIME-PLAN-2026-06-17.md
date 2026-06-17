# Mode-Orchestrated Runtime Plan — QN19 — 2026-06-17

Status: first implementation slice landed after `qn19-early-gui-2026-06-17`.

This is the larger task that should group the next related changes. The goal is
not another isolated boot tweak; the goal is to make the selected product mode
own runtime resources.

## Product Modes

| Mode | Product meaning | Allowed baseline work | Must stay off |
|------|-----------------|-----------------------|---------------|
| `playnow` | Default. Car Thing is a fast media/control surface for the iPhone. | DRM/GUI, input, BLE pairing/reconnect, AMS/ANCS/CTS/metadata/control, notifications, runtime state publish. | speaker standby loop, receiver paging, A2DP source routing to speakers, route patchbay activation, speaker scans unless user starts pairing. |
| `commutator` | Full audio switchboard/router. | Everything in Play Now plus explicit route graph, selected speaker standby/connection, A2DP sink/source, AVRCP backchannel, codec/relay path. | hidden routes not requested by the active session. |
| `reserved` | Future USB-oriented slot. | For now behaves like Play Now. | Bluetooth switchboard behavior unless the future USB session explicitly asks for it. |

## Implemented Slice — 2026-06-17

- `operation_mode.py` defines the product modes and an explicit
  `ModeResources` contract.
- `AppState.operation_mode` defaults to `operation_mode.DEFAULT` (`playnow`).
- `RuntimeModel.bt_block()` publishes `operation_mode` and `mode_resources`.
- `TransferService.apply_operation_mode()` owns standby-loop, receiver-stream,
  speaker-scan and local-sink teardown for Play Now.
- `carthing_runtime._apply_operation_mode()` is the single runtime path used by
  boot, settings, and route activation.
- Selected external route activation intentionally enters `commutator`; Play Now
  selection returns to `playnow`.
- `scripts/check-operation-mode-contract.py` is included in
  `scripts/check-bake-readiness.sh`.
- QN19 live proof after reboot: `operation_mode=playnow`,
  `speaker_standby=false`, `receiver_stream=false`, `route_patchbay=false`,
  `speaker_scan=false`, and all commutator `actual_*` indicators false.

## Current Remaining Code Facts

- AVDTP listener still starts at boot as a transitional compatibility baseline.
  It is published separately as `a2dp_listener=true` and `actual_a2dp_listener=true`.
- `transfer_active` remains a legacy broad flag and should not be used as proof
  that a speaker route is active.
- Full Play Now -> Коммутатор -> Play Now route-load proof remains the next live
  slice before lazy-starting the AVDTP/SDP surface.

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

## Additions From `carthing_analysis.md` And Ideas Log

These items should be folded into the same workstream because they are mode
ownership problems, not independent UI tweaks.

8. **Mode resource telemetry**
   - Publish and log whether commutator-only resources are running:
     `standby_loop`, `receiver_stream`, `a2dp_listener`, `route_patchbay`,
     `speaker_scan`, `usb_profile`.
   - Track proof counters per boot/session: page attempts, `PAGE_TIMEOUT`, HCI
     busy/retry events, active route output, and selected-vs-active route.
   - Acceptance: in Play Now, proof logs show no background speaker paging and no
     receiver loop unless pairing or route activation explicitly requests it.

9. **Per-mode CPU/DVFS policy**
   - `carthing_analysis.md` identifies `performance` governor as wasteful for the
     default control-surface mode.
   - Add a guarded CPU policy layer after mode ownership exists:
     Play Now can use a low/elastic governor or capped frequency, while
     Коммутатор can temporarily raise frequency for route activation, codec work,
     and heavy render bursts.
   - Acceptance: record governor/frequency in runtime proof and verify no UI or
     AMS regression before baking.

10. **Commutator audio throughput proof**
   - The analysis highlights the Bluetooth UART bandwidth problem and the fwload
     3 Mbit/s path. The repo currently has `CARTHING_BT_INIT_BACKEND=attach`
     while also carrying fwload tooling.
   - Treat this as a Коммутатор prerequisite, not as a Play Now boot dependency:
     first prove the live HCI UART speed and A2DP throughput under route load,
     then decide whether the product image should switch to fwload or keep the
     current attach path.
   - Acceptance: route activation proof must include no sustained RTP drops caused
     by UART/HCI bandwidth.

11. **Reserved mode as USB profile owner**
   - The analysis maps ConfigFS USB profiles (`ncm`, `ncm+audio`, `hid`,
     `mass_storage`, `rndis`, `midi`, `ncm+hid`).
   - Keep `reserved` equivalent to Play Now until USB mode work starts, but model
     it as the future owner of USB profile/session resources.
   - Any USB profile switch that can disrupt SSH/NCM must be gated, visible in UI,
     and reversible through the rescue path.

12. **Mode-aware power and safe-unplug**
   - Safe unplug is not a Linux `poweroff`; it is a mode/resource teardown:
     stop route, stop standby/pairing/scans, sync state, make persistent storage
     safe, then show that physical USB power can be removed.
   - The same resource-stop code should be reused by mode switches and safe
     unplug, rather than maintaining separate partial teardown paths.

13. **Sensor-assisted UI/power policy**
   - ALS/proximity can belong to the Play Now resource set: auto-brightness,
     dim-on-away, wake-on-approach.
   - This should come after mode ownership because it changes render/power
     behavior and needs proof against touch/input usability.

## Explicitly Deferred From This Workstream

- p3/ext4 state migration: valuable research, but not part of the current P1/P2
  product baseline unless reopened explicitly with a recovery plan.
- custom ThingLabsOSS U-Boot/FIP: useful for research, on-panel boot menus, or
  full GPT freedom, but not required for the current Play Now/Коммутатор runtime
  optimization.
- VPU/video, OSD2, VAD/voice, eBPF, HW crypto, ZRAM: keep as capability backlog.
  They should not block the mode owner unless a specific product feature needs
  them.

## Acceptance Criteria

- Cold boot default is Play Now in settings, GUI, runtime JSON, and logs.
- In Play Now, no speaker standby loop or receiver paging runs unless pairing or
  route activation explicitly requests it.
- Коммутатор starts only through explicit mode/route action and tears down cleanly.
- Резерв does not accidentally start Bluetooth switchboard work.
- Runtime proof includes mode resource state and HCI/page counters sufficient to
  prove the system is actually quieter in Play Now.
- CPU/frequency policy changes are gated by mode and backed by live proof, not
  assumed from theory.
- USB profile ownership is reserved-mode aware and does not strand normal
  NCM/SSH access without a recovery path.
- `scripts/check-bake-readiness.sh` catches regressions in the mode contract.
- The final state is baked into `image/rootfs.img`, verified on QN19, committed,
  and tagged as the next product baseline.
