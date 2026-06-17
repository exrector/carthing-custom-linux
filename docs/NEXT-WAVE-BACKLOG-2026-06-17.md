# Next Wave Backlog — QN19 — 2026-06-17

Status: consolidated working backlog after tag
`qn19-mode-owned-runtime-2026-06-17`.

Purpose: keep every useful idea visible, but stop looping over work that is
already done. Do not delete historical tasks from source documents. When a task
is complete, mark it as `DONE` and keep the original wording or a faithful
short form.

Important: this backlog is an option board, not an execution mandate. Items are
not automatically "required" just because they are listed here. Before
implementation, each `NEXT`/`RESEARCH` item must be re-judged against the real
product goal: innovation, measurable optimization, lower runtime load, faster
perceived boot, better reliability, or clearer architecture. If an item is only
"nice to have" or adds complexity without a strong product payoff, keep it
visible but do not implement it in the current wave.

## Sources Read

- `carthing_analysis.md`
- `ПЛАН-ПРИОРИТЕТЫ.md`
- `docs/RUNBOOK-NEXT.md`
- `docs/MODE-ORCHESTRATED-RUNTIME-PLAN-2026-06-17.md`
- `docs/PRODUCT-BASELINE-2026-06-17-QN19.md`
- `~/.Codex/projects/-Users-exrector/memory/ideas-log.md`
- `~/.codex/memories/MEMORY.md`

## Status Legend

- `DONE` — implemented, verified, committed/tagged or otherwise proven.
- `PARTIAL` — the direction is implemented, but one important proof or slice is
  still missing.
- `NEXT` — good candidate for the next implementation wave.
- `DEFERRED` — valuable, but not part of the current low-risk product wave.
- `RESEARCH` — needs proof before product integration.
- `REJECTED` — keep the idea visible so we do not resurrect it accidentally.

## Current Baseline

- `DONE` — product baseline tag:
  `qn19-mode-owned-runtime-2026-06-17`.
- `DONE` — P1/P2 architecture is the current product line.
- `REJECTED` — p3/ext4 persistent-state migration is not part of the current
  product baseline unless explicitly reopened with a recovery plan.
- `DONE` — permanent macOS USB/NCM access watchdog:
  `com.exrector.carthing.usb-route-watch`.
- `DONE` — Claude Code CLI restored:
  `claude --version` reports `2.1.179`; installed with
  `npm install -g --prefix /opt/homebrew @anthropic-ai/claude-code@latest`.

## Already Done — Keep Visible

- `DONE` — ~~CPU/boot Android cleanup: remove `reboot_mode_android`,
  `androidboot.*`, `jtag`, `uboot_version` from bootargs/env contract.~~
  Closed by `qn19-bootargs-clean-2026-06-17`.

- `DONE` — ~~First product signal is early DRM/GUI home shell before heavy
  Bluetooth/Bumble init.~~
  Closed by `qn19-early-gui-2026-06-17`.

- `DONE` — ~~Mode-Orchestrated Runtime first slice: Play Now, Коммутатор, and
  Резерв are explicit product modes with resource contracts.~~
  Closed by `qn19-mode-owned-runtime-2026-06-17`.

- `DONE` — ~~Separate desired mode contract from actual runtime resource state:
  `speaker_standby` vs `actual_standby_loop`,
  `receiver_stream` vs `actual_receiver_stream`,
  `route_patchbay` vs `actual_route_patchbay`, etc.~~
  Closed by `qn19-mode-owned-runtime-2026-06-17`.

- `DONE` — ~~Permanent USB/NCM access instead of manual route repair.~~
  Closed by `scripts/carthing-usb-route-watch-macos.sh` and
  `scripts/install-carthing-usb-route-watch-macos.sh`; launchd proof repaired
  `172.16.42.77` from `utun9` back to `en18`.

- `DONE` — ~~Safe unplug wording: GUI action means prepare for physical USB
  power removal, not Linux `poweroff`/`halt`.~~
  Implemented in current product behavior and documented as product policy.

- `DONE` — ~~Logo slot: use `bootup_spotify`, not generic `bootup`.~~
  Verified visually by owner.

- `DONE` — ~~HWRNG `/dev/hwrng` feeds entropy.~~
  `ПЛАН-ПРИОРИТЕТЫ.md` marks this as done by kernel behavior.

- `DONE` — ~~UART speed: `btattach-mini` already switches Bluetooth UART to
  3 Mbit/s; fwload is not required just for speed.~~
  Keep only throughput proof as remaining work.

- `DONE` — ~~GE2D kernel/device availability: `/dev/ge2d` exists on live QN19.~~
  Remaining work is GUI/lib integration, not basic device enablement.

- `DONE` — ~~From-zero GitHub user path: install flashing tools, enter burn
  mode, flash, bring up USB/NCM, SSH, sanity checks, rebuild rootfs.~~
  Covered by `docs/GETTING-STARTED-FROM-ZERO.md`, but can still be refined for
  readability.

## Next Wave A — Low-Risk Product Improvements

These are the best candidates for a single broad implementation wave now. They
are aligned with the mode-owned runtime baseline and mostly use sysfs/runtime
policy, not risky partitioning or bootloader work.

### A1. Per-Mode CPU/DVFS Policy

Status: `PARTIAL live 2026-06-17`

Local implementation note:
`resource_policy.py` now applies a conservative mode-aware CPU governor policy
and publishes accepted governor/frequency diagnostics through runtime state.
Play Now prefers `schedutil`; Коммутатор can request `performance` when the
kernel supports it. QN19 live+reboot proof confirms Play Now governor
`performance -> schedutil` and runtime-state publication. This is not fully
`DONE` until Коммутатор route activation proof confirms boost/release behavior.
Proof: `docs/RESOURCE-POLICY-PROOF-2026-06-17.md`.

Original idea preserved:
CPU governor `performance` -> `schedutil`; live QN19 showed all four cores at
1800 MHz 24/7 while `schedutil` is available. Expected value: cooler default
Play Now mode, lower idle power, fewer background spikes.

Implementation shape:
- Add small runtime/system policy helper, not ad hoc shell writes.
- Play Now: `schedutil` or conservative cap.
- Коммутатор: temporary boost during route activation, codec/transcode work,
  and heavy render bursts.
- Publish proof in runtime state: governor, current/min/max frequency, policy
  owner, last transition reason.
- Add local test that rejects unsupported governors gracefully.

Acceptance:
- Live QN19 proof in Play Now: governor changed, GUI/AMS still responsive.
- Коммутатор route activation can request boost and then release it.

### A2. ZRAM 128 MB As Safety Margin

Status: `DONE live 2026-06-17`

Local implementation note:
`S11-zram` now enables `/dev/zram0` as 128 MB swap and exits successfully if
zram or swap tools are unavailable. QN19 live+reboot proof shows `/dev/zram0`
active in `/proc/swaps`, algorithm `[lzo] deflate`, zero used swap at boot, and
runtime-state `resource_policy.zram.active=true`.
Proof: `docs/RESOURCE-POLICY-PROOF-2026-06-17.md`.

Original idea preserved:
ZRAM exists (`CONFIG_ZRAM=y`) but `disksize=0` and swap is off. Add 128 MB
`lzo-rle` swap as anti-OOM reserve.

Implementation shape:
- Add init script or product policy script.
- Use existing kernel support; no rebuild.
- Keep swappiness conservative.
- Publish `zram_enabled`, size, algorithm, swap usage in diagnostics.

Acceptance:
- Live QN19 shows `/proc/swaps` with zram.
- No boot slowdown or runtime regression.

### A3. Mode-Aware Safe Unplug Reuse

Status: `PARTIAL live 2026-06-17`

Local implementation note:
The GUI power action now sends the runtime through the central
`_apply_operation_mode(playnow, reason="safe_unplug")` path before launching the
safe-unplug finalizer. `power_control.prepare_for_usb_unplug()` also publishes
clearer states: `preparing -> stopping_routes -> syncing -> ready_to_unplug`.
Deployed on QN19, but intentionally not marked `DONE` until a real safe-unplug
test is performed with the owner ready to remove/reapply USB power.
Proof so far: `docs/RESOURCE-POLICY-PROOF-2026-06-17.md`.

Original idea preserved:
Safe unplug is a mode/resource teardown: stop route, stop standby/pairing/scans,
sync state, make persistent storage safe, then show that physical USB power can
be removed. Do not use Linux `poweroff`/`halt`.

Implementation shape:
- Reuse `_apply_operation_mode(playnow)` / `TransferService.apply_operation_mode`
  for stopping commutator resources.
- Add explicit safe-unplug state machine:
  `preparing -> stopping_routes -> syncing -> storage_safe -> ready_to_unplug`
  or `error/escalating`.
- Keep screen/error state visible if preparation fails.
- Add recovery path if power is not removed.

Acceptance:
- Live proof: route/standby/scan stopped, state synced, no Linux halt, clear UI
  message.

### A4. ALS/Proximity Sensor Policy

Status: `PARTIAL live 2026-06-17`

Local implementation note:
`resource_policy.py` now publishes TMD2772 ALS/proximity diagnostics in
runtime-state without changing brightness automatically. QN19 live proof shows
`als_prox_present=true`, `illuminance_input=1`, and `proximity_raw=0`. This is
kept `PARTIAL` because the actual product policy (auto brightness, wake/dim, or
proximity behavior) still needs a measured threshold decision.
Proof: `docs/RESOURCE-POLICY-PROOF-2026-06-17.md`.

Original idea preserved:
ALS/proximity IIO device exists. Use `in_illuminance0_input` for auto-brightness
and `in_proximity0_raw` for wake/dim behavior.

Implementation shape:
- Python-only sensor reader with smoothing/hysteresis.
- Respect manual brightness and never write raw backlight outside
  `power_policy`.
- Treat sensor policy as part of Play Now resource set.

Acceptance:
- Live sensor values logged/published.
- No black-screen regression; brightness stays clamped by existing policy.

### A5. Route-Load Proof: Play Now -> Коммутатор -> Play Now

Status: `NEXT`

Original idea preserved:
Full proof must cover cold boot Play Now, switch Play Now -> Коммутатор,
selected route activation/deactivation, and return to Play Now.

Implementation shape:
- Add a host proof script that captures:
  runtime-bt JSON, route fields, mode resources, packets forwarded/dropped,
  HCI/page timeout counters, log markers.
- Use current route hardware first: iPhone + known-good Fosi.
- Append results to `docs/route-test-series-results.md`.

Acceptance:
- In Play Now, actual commutator resources remain false.
- In Коммутатор with active route, only selected output is active.
- Returning to Play Now tears down receiver/standby/patchbay.

### A6. Input Pairing Enrollment Window

Status: `NEXT`

Original idea preserved:
IN+ pairing must be its own enrollment window. Existing trusted iPhone sticky
reconnect must not close the modal or occupy advertising before the new input
is enrolled.

Implementation shape:
- On IN+, temporarily disconnect known LE peers.
- Track expelled peers and reject/throttle their reconnect until enrollment
  ends.
- Close pairing only after AMS/ANCS enrollment and card write, not after first
  LE connection.

Acceptance:
- New iPhone/Mac input can be enrolled without old iPhone stealing the window.
- No HCI `COMMAND_DISALLOWED` storm.

### A7. Device Passport / Per-Role Readiness

Status: `NEXT`

Original idea preserved:
Multirole device must be one card with role-specific endpoints and readiness:
input-ready via AMS/ANCS is not output-media-ready if AVDTP sink is absent or
degraded.

Implementation shape:
- Extend device cards with per-role readiness blocks.
- Route planner reads role readiness, not just global trusted presence.
- Degraded devices like AirFly must not block baseline route matrix.

Acceptance:
- Nebula-style multirole device remains one card.
- AirFly-like degraded output is quarantined from normal route activation unless
  explicitly tested.

## Next Wave B — Medium / Architecture Work

### B1. Lazy AVDTP/SDP Startup

Status: `PARTIAL`

Original idea preserved:
In Play Now, avoid starting commutator-only background loops. Decide by proof
whether AVDTP listener/SDP setup is still needed at boot or should be
lazy-started only when user activates a route.

Current state:
- Standby/receiver/scan/patchbay are gated.
- AVDTP listener still starts at boot as transitional compatibility surface.

Next:
- Prove iPhone/AMS behavior when AVDTP listener is lazy.
- If safe, move SDP/AVDTP listener into commutator activation.

### B2. Commutator Audio Throughput Proof

Status: `NEXT`

Original idea preserved:
UART is already 3 Mbit/s, so the real task is proving A2DP throughput under
route load, not replacing attach with fwload prematurely.

Implementation shape:
- Capture packets forwarded/dropped under sustained route.
- Include render cadence and CPU governor state.
- Decide whether current attach path is enough.

### B3. Zero-Config Transcode Hub

Status: `DEFERRED` for product wave, `RESEARCH/NEXT` for audio sub-branch

Original idea preserved:
User should never know codecs. Device capabilities decide passthrough vs
transcode. If source/receiver codecs differ, Car Thing converts in machine
code/HW; if they match, bypass.

Known pieces:
- libsbc encode/decode exists.
- T9015/local sink path exists as hidden debug/bonus capability.
- AAC decode remains the major gate.

Next:
- Do not expose dead UI endpoints.
- First prove AAC decode path or fallback lightweight decoder.

### B4. GUI/BT/Audio Process Isolation

Status: `DEFERRED`, design first

Original idea preserved:
Separate GUI process from BT/audio runtime, mount cpuset, use scheduling/IRQ
affinity: OS/IRQ, GUI, BT/UART, audio.

Current facts:
- cpuset is compiled but not mounted.
- This is architecture-level and should start with design/protocol, not a blind
  refactor.

Next:
- Write process-boundary design: snapshot protocol, intents, Unix socket,
  failure/restart behavior.

### B5. GE2D / Dirty Rect GUI Optimization

Status: `RESEARCH -> NEXT after proof`

Original idea preserved:
Use `/dev/ge2d` for 2D blit/scale/alpha and dirty rectangles in
`libcarthing_frame.so`, redrawing only changed areas.

Next:
- Build or locate `libge2d` userspace path.
- Create minimal live blit proof outside the main GUI.
- Only then integrate into render path.

## Next Wave C — UX and Feature Work

### C1. Terminal UI Remaining Polish

Status: `PARTIAL`

Original idea preserved:
Terminal-style modal pairing and trusted-devices screens need a full pass;
block cursor / READY line should be discussed, not silently added.

Next:
- Preview both terminal and dark themes.
- Keep logic out of style-only changes.

### C2. Multitouch Gestures

Status: `NEXT/UX`

Original idea preserved:
Use touch MT-B gestures: swipe track change, long-press presets, maybe pinch.

Guardrail:
- Must not collide with existing route/settings gestures.

### C3. DRM Multiplane / OSD2 Overlay

Status: `RESEARCH`

Original idea preserved:
Use DRM planes for call/notification/debug overlays without repainting the main
UI.

Next:
- Probe plane availability with DRM tooling.
- Prove a small overlay outside runtime.

### C4. USB Reserved Mode Owner

Status: `DEFERRED`

Original idea preserved:
Reserved mode is future owner of USB profiles (`ncm`, `ncm+audio`, `hid`,
`midi`, `mass_storage`, `rndis`, etc.).

Guardrail:
- Any profile switch that can disrupt SSH/NCM must be visible, reversible, and
  rescue-safe.

## Research / Deferred Capability Backlog

### R1. iAP2 / MFi

Status: `RESEARCH`

Original idea preserved:
MFi cert is readable from i2c-3:0x10; kernel module ABI mismatch exists;
userspace driver may unlock iAP2 paths. Artwork/library browsing have already
been disappointing and must not be assumed.

Next:
- Define what we actually need beyond AMS/ANCS before writing code.

### R2. Voice / PDM / VAD

Status: `RESEARCH`

Original idea preserved:
4-mic PDM array plus offline STT/wake-word could make the device a voice
surface. HW VAD exists but ioctl path is proprietary/unknown.

Next:
- Separate hardware capture proof from assistant/product UX.

### R3. VPU / Hardware Video

Status: `RESEARCH`

Original idea preserved:
AVE-10/VPU may decode video cheaply through media devices.

Next:
- Keep out of current audio/runtime optimization wave.

### R4. U-Boot / FIP / GPT Freedom

Status: `RESEARCH`

Original idea preserved:
ThingLabsOSS `superbird-uboot` and `superbird-fip-tools` may help with boot
menus or full GPT freedom.

Decision:
- Not needed for the current P1/P2 product baseline.
- Only reopen with ramboot/recovery proof and measurable boot improvement.

### R5. p3/ext4 State

Status: `REJECTED for current baseline`, `RESEARCH only`

Original idea preserved:
p3 ext4 state partition was considered for journaled state.

Decision:
- Current product line is P1 FAT boot+small state and P2 readonly rootfs.
- Do not resurrect p3 unless the owner explicitly reopens it with recovery plan.

## Proposed Big Fan for the Next Implementation Run

If we want a coherent broad implementation wave now, do these together:

1. `A1` Per-mode CPU/DVFS policy.
2. `A2` ZRAM safety margin.
3. `A3` Safe unplug reusing mode teardown.
4. `A4` ALS/proximity policy through existing `power_policy`.
5. `A5` Route-load proof script and append-only results.

Rationale: these are mutually reinforcing and low-risk. They improve the
default Play Now product feel and give proof infrastructure before we attempt
harder work like lazy AVDTP startup, native transcode, process isolation, or
GE2D GUI integration.

## Claude Desktop / Claude Code Note

- Claude.app is the richer interactive GUI surface.
- For this agent to delegate work programmatically, the reliable interface is
  still the `claude` CLI.
- Local state fixed on 2026-06-17:
  `npm install -g --prefix /opt/homebrew @anthropic-ai/claude-code@latest`
  restored `/opt/homebrew/bin/claude`, version `2.1.179`.
- The previous npm global install existed under Homebrew Node Cellar paths, but
  did not expose `claude` on the stable shell `PATH`.
