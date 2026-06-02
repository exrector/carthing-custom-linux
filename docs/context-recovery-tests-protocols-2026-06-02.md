# Car Thing context recovery: tests, protocols, deferred ideas

Date: 2026-06-02.

Purpose: recover the practical contract from project history before more
release implementation. This document is intentionally biased toward things
that are hard to reconstruct quickly: live tests, protocol bring-up results,
negative findings, deferred ideas, and architectural decisions that explain how
devices are supposed to work together.

## Sources Read

Primary sources:

- `carthing-release-architecture/docs/TRANSCRIPT-DIGEST.md`
- `carthing-release-architecture/docs/CONSOLIDATION.md`
- `carthing-release-architecture/docs/ARCHITECTURE-REALIZED.md`
- `carthing-release-architecture/docs/RELEASE-PLAN.md`
- `carthing-release-architecture/docs/pairing-and-transfer-scenarios.md`
- `carthing-release-integration/docs/route-graph-architecture-2026-06-01.md`
- `carthing-release-integration/docs/userspace-rebuild-plan-2026-06-01.md`
- `carthing-release-integration/docs/device1-v1-working-baseline-2026-05-18.md`
- `carthing-release-integration/docs/device1-reliability-pass-2026-05-18.md`
- `carthing-release-integration/docs/checkpoint-2026-05-18-hid-pair-cold-boot.md`
- `.Codex/projects/-Users-exrector/memory/carthing-claude-usb-audio-target-20260528.md`
- `.Codex/projects/-Users-exrector/memory/carthing-claude-intervention-20260528.md`
- `.codex/memories/MEMORY.md`
- `.codex/memories/rollout_summaries/*carthing*.md`
- `.claude/projects/-Users-exrector/memory/carthing-*.md`
- `.claude/projects/-Users-exrector/memory/feedback_carthing_*.md`
- current `carthing-release-integration` runtime modules:
  `accessory_orchestrator.py`, `transfer_service.py`,
  `trusted_device_registry.py`, `enrollment_manager.py`,
  `route_planner.py`, `session_runner.py`, `session_presets.py`.

Large upstream/vendor trees were excluded from semantic search after confirming
they swamp the result set with kernel/vendor documentation. Device backup docs
and logs were still included where they are author-written project artifacts.

## Non-Negotiable Contract

### One logical Bluetooth accessory

Car Thing must be one logical accessory, not separate BLE and Classic personas.

The visible identity is factory identity, not MAC-derived:

- source of truth: `/sys/class/efuse/usid`
- observed USID: `8559RP88Q917`
- public name: `Car Thing (SN: Q917)`
- same name should flow through hostname, BLE local name, Classic local name,
  logs, and UI.

Rejected names:

- `CarThing-<MAC>` for normal operation
- `Car Thing Audio`
- second Classic-only persona shown as a separate user-facing device

MAC may remain a low-level fallback only when efuse/config identity is absent.

### BlueZ is legacy evidence only

Do not revive BlueZ, `bluetoothctl`, `sdptool`, D-Bus profile registration,
PAN/SPP recipes, or BlueZ-based workflows for current Car Thing work. The
release path is Bumble/raw HCI/custom binaries/kernel primitives.

Old BlueZ references in stock firmware or early docs can explain history, but
they are not an implementation path.

### Classic hardware on, Classic connectability gated

Classic BR/EDR hardware must be initialized on every boot because CTKD needs
Classic available during the first LE pairing. That does not mean the device is
connectable or discoverable.

Correct invariant:

```text
boot: Classic hardware on
REMOTE / idle: Classic connectable=false, discoverable=false
TRANSFER activation: Classic connectable=true, discoverable=false
Pairing mode: BLE general advertising on by deliberate user intent
```

Classic discoverable should stay false. The iPhone should get its Classic
link-key through CTKD from the BLE pairing, then connect Classic silently when a
Transfer route is deliberately active.

### Pairing is one-time enrollment

Daily usage should not require re-pairing. Enrollment is the heavy step:

- scan the peer as deeply as possible;
- pair/bond all supported transports the peer permits;
- classify source/sink/control/metadata/notification capabilities;
- write one trusted device record with endpoints and constraints;
- save as ready only after required proof exists, or save degraded with explicit
  missing capabilities.

The user-facing Settings path should be one broad action: add Bluetooth device.
The old split between source and speaker is a transitional UI shortcut only.
Inputs and Outputs are views over one device registry.

### Transport-changing actions require deliberate activation

Normal tap selects/focuses. Long tap or an explicit connect command activates a
route, starts pairing, or changes transport state. This came from a live UX
failure where accidental taps activated modes while swiping.

## Device Roles And Data Flows

### iPhone as media/control/notification peer

The iPhone is primarily:

- BLE AMS metadata source;
- BLE AMS control target for play/pause/next/previous/volume;
- BLE ANCS notification source;
- BLE CTS time source;
- optional Classic A2DP audio source only when Transfer is active.

Important: Play Now metadata should continue over BLE AMS even when Transfer is
active. Transfer routes audio; it should not replace the metadata/control
surface.

Expected REMOTE flow:

```text
iPhone BLE AMS/ANCS/CTS/HID
  -> Car Thing RuntimeModel / AppState
  -> DRM UI

Car Thing encoder/buttons
  -> AMS command over BLE
  -> iPhone system media session
```

### Transfer audio flow

Expected Transfer flow:

```text
iPhone
  -> Classic A2DP source stream
  -> Car Thing A2DP sink socket
  -> relay / passthrough path
  -> Car Thing A2DP source socket
  -> trusted speaker such as Fosi
```

The intended relay is AAC passthrough where possible. T9015 analog playback is
not required for the Fosi/receiver route. The Car Thing becomes a digital router
and control surface, not a DAC in this path.

### Speaker/Fosi role

Fosi ZD3 is an audio output and may also be a control producer. Its remote or
AVRCP/pass-through buttons should not connect to iPhone directly. They should
route through Car Thing:

```text
Fosi button / AVRCP
  -> Car Thing TransferControlBackchannel
  -> normalized command
  -> AMS command over BLE
  -> iPhone
```

That gives one control graph with three devices in the chain. Metadata remains
on Car Thing via AMS.

### Mac role

Mac can be source, sink, control peer, or USB-audio peer depending on exposed
endpoints and constraints. Do not hardcode it as one role. The route graph
should decide based on available endpoints.

USB-C audio target:

```text
Mac UAC2 playback
  -> CarThingUAC2 ALSA capture side
  -> userspace bridge
  -> T9015 playback, external route, or recorder/debug sink

PDM microphone
  -> userspace bridge
  -> CarThingUAC2 ALSA playback side
  -> Mac UAC2 capture
```

The UAC2 gadget enumeration was confirmed, but the audio bridge is still the
blocking userspace work.

## Proven Tests And Evidence Matrix

### 2026-05-03 BLE/AMS recovery

Status: proven enough to become recovery baseline.

Evidence:

- commit `01ac6df` was the April 19 working app payload;
- active path used Bumble over `serial:/dev/ttyS1,3000000`;
- Bumble `host.py` bug fixed on-device: `event.latency` was wrong, should be
  `event.max_latency`;
- `media_remote_v3.py` was active with heartbeat, re-advertise, and GATT ping;
- do not treat log silence as disconnect; check connection count and heartbeat.

Operational detail:

- `BindInterface=en14` was needed for SSH when VPN routing hijacked
  `172.16.42.0/24`;
- local HTTP proxy on `172.16.42.1:8888` was used for package install.

### 2026-05-11 iAP2 live bring-up

Status: partial research; not release blocker.

Confirmed:

- live device reached HCI/ACL/RFCOMM/SSP/auth/identification;
- problem was iAP2 contract, not basic Bluetooth bring-up;
- `AA05 auth success`, `1D02 IdentificationAccepted`, `0x6800 StartHID`, and
  `0x40C8 StartNowPlaying` were observed in some branches;
- `EA02` with `com.spotify.client` did not produce the expected `EA00`;
- `0x000A` in Identification was rejected:
  `1D03 rejected param id=0x000a`;
- clean-room iAP2 should omit `0x000A` in minimal identification and reintroduce
  fields one at a time.

Useful knobs:

- `CARTHING_IAP2_ID_MSGSET`
- `CARTHING_IAP2_POST_ID_MODE`
- `CARTHING_IAP2_EA_PROTOCOL`
- `CARTHING_IAP2_APP_LAUNCH_UTI`
- `CARTHING_IAP2_EA_MATCH_ACTION`

Deferred:

- NowPlaying-only / EA contract narrowing;
- app-launch identifiers;
- iAP2 app-launch and broader MFi research.

### 2026-05-18 Device1 V1 working baseline

Status: proven end-to-end after real cold boot on device 1.

Guaranteed:

- only `rootfs.img` replaced; bootfs/env/bootloader/kernel/dtb inherited;
- SSH, password fallback, httpd, telnetd, reverse-agent ingress worked;
- firmware stage, `carthing-btattach-mini`, kernel `hci0`, HID pairing identity,
  and AMS runtime on Bumble `hci-socket:0` worked;
- bond keys persisted across reboot on `mmcblk0p1`.

Live after cold boot:

- already-paired iPhone reconnected automatically;
- GUI returned without manual intervention;
- podcast metadata appeared;
- encoder worked;
- USB ingress could be recovered on macOS after normal boot.

Canonical rootfs:

- `artifacts/flash-device1-attach/rootfs.img`
- SHA-256 `8f2e84cdc22a750098f87598255ba5f77c1d8d0b9f8e671535aefdca0129dcdd`

Canonical commit chain:

- `0103346`
- `5021eb3`
- `eb649e8`
- `0bfec2a`

Reliability pass still desired:

- 3-5 cold boots;
- iPhone Bluetooth off/on;
- phone reboot;
- USB service check.

### 2026-05-19 services experiment

Status: implementation branch, not fully merged.

Implemented in experiment:

- ANCS client;
- CTS client;
- HID keyboard extension / consumer control;
- CarThingLink custom GATT skeleton;
- BAS refinement;
- MTU 247;
- touch/input mapping.

User directives:

- iAP2 is not needed for music; AMS + BLE HID is enough for media remote;
- iAP2 clean-room research through physical MFi auth chip is allowed but is not
  a production blocker;
- no slots; one device, one process, multiple views/desktops/surfaces;
- notifications should be quiet UI state, not intrusive banners;
- no fake workarounds for missing hardware.

Hardware facts from this pass:

- PDM microphone exists, capture-only;
- no proven playback device in that state (`pcmC0D0c` present, `pcmC0D0p`
  absent at the time);
- TMD2772 ALS/proximity works;
- LIS2DH12 present but no driver;
- MFi chip on i2c-3 address `0x10`;
- event3 touchscreen is tlsc6x MT protocol B, 2 touches max, 480x800,
  approximately 83 Hz;
- touch transform: `canvas_x=touch_y`, `canvas_y=479-touch_x`;
- long press must be timer-derived because hold events do not continue.

### 2026-05-22 identity, visibility, and cold-boot regression

Status: key product lessons.

Resolved:

- factory identity from efuse replaced MAC-derived naming;
- bonded-only undirected BLE advertising still exposes name and HID UUID to
  scans; filter policy does not hide advertising;
- proper idle visibility is directed advertising to a BLE-bonded peer or full
  silence when no BLE bond exists;
- general discoverable is only for deliberate pairing mode;
- classic link-key alone is not enough for BLE directed reconnect.

Observed regression:

- after power-cycle, runtime could fail with `OSError Errno16 HCI busy`;
- root cause: runtime started before `hci0` was ready from btattach and S50 did
  not self-heal;
- this became the seed for conductor/self-heal.

Important implementation guard:

- If `keys.json` contains only Classic link-key, AMS BLE reconnect is not
  recovered. Need LE LTK/IRK too.

### 2026-05-24/25 dual-mode and CTKD decision

Status: agreed architecture theory, partly implemented.

Decision:

- dual-mode accessory should be one pairing contract with CTKD, not two visible
  devices;
- BLE first pairing should derive/store LE keys and BR/EDR link-key when the
  peer supports it;
- A2DP/Transfer activates manually from Car Thing;
- iPhone must not auto-connect as a speaker in default REMOTE;
- Fosi AVRCP/backchannel is wanted, not a bug;
- route graph and orchestrator above Bumble are the right layer.

Current code implements the keydist insight in
`accessory_orchestrator.py`: key distribution includes
`SMP_LINK_KEY_DISTRIBUTION_FLAG`. Existing iPhone bonds created before this
must be forgotten and re-created once to get the Classic key through CTKD.

### 2026-05-28 USB composite/UAC2

Status: UAC2 enumeration proven; audio bridge missing.

Confirmed live:

- composite gadget switching `ncm -> ncm,audio -> ncm -> ncm,audio -> ncm`
  worked without phantom UAC2 after teardown fix;
- macOS saw a real class-compliant UAC2 device:
  `Output Channels: 2`, `Input Channels: 2`, `Transport: USB`;
- `AppleUSBAudioControlNub` bound when active;
- NCM remained present through tested profile cycles.

Kernel 4.9 caveats:

- several newer UAC2 configfs attrs are absent: `c_sync`, `function_name`,
  mute/volume attrs;
- `c_srate` displayed `64000` despite attempted `48000`;
- Mac still enumerated full-duplex UAC2.

Blocking work:

- add `alsa-utils` or equivalent userspace bridge tooling to rootfs;
- integrate `carthing-uac2-bridge.sh` or equivalent;
- connect `profilectl usb set ncm,audio` to bridge start/stop;
- investigate `c_srate=64000`.

### 2026-05-29 USB disk mode

Status: mechanics tested by Claude; runtime integration still needed.

Confirmed:

- `usb-disk-mode enter ro|rw`, `exit`, `status`, `watch` was built on the live
  device;
- raw `/dev/mmcblk0p1` can be exported via mass storage;
- macOS can mount it read-only and read-write;
- write round-trip to the real partition worked after exit;
- NCM survived profile switching.

Kernel/configfs lessons:

- `lun.0/ro` must be written before `lun.0/file`;
- unload media with `echo "" > file` before changing `ro`;
- direct blind `echo "" > UDC` can hang the kernel; use the profile wrapper.

Remaining runtime work:

- guard screen while `/run/carthing/usb-disk-active` exists;
- system menu action must start it in background without `os._exit(75)`;
- runtime must release `/run/carthing-state` cleanly before raw export.

### 2026-06-01/02 route graph refactor

Status: local smoke proven; live route behavior still must be tested.

Implemented locally:

- unified `TrustedDeviceRegistry` schema v2;
- legacy `sources` and `speakers` read as compatibility views;
- `EnrollmentManager` builds capabilities/endpoints/constraints from evidence;
- `RoutePlanner` rejects some full-duplex/exclusive-resource conflicts;
- `SessionRunner` owns start/stop order and connector detach/stop;
- `session_presets` maps old modes to sessions/presets;
- smoke route graph passes locally: `ROUTE GRAPH SMOKE OK`.

Important limitation:

- current smoke tests prove model mechanics, not live Bluetooth pairing or real
  Fosi strict auth/encrypt/link-key behavior.

## Current Intended Runtime Model

Top-level architecture:

```text
TrustedDeviceRegistry
  -> EnrollmentManager
  -> LinkManager
  -> RoutePlanner
  -> SessionRunner
  -> AdapterConnectors
```

User-facing model:

- devices are enrolled once;
- the GUI shows Inputs and Outputs as filtered views over one registry;
- the user chooses input resource and output resource;
- the planner builds a session graph;
- the runner stops current session, releases exclusive resources, starts needed
  adapters, and publishes state;
- lower adapters handle Bumble/HCI/A2DP/AVRCP/AMS/ANCS/USB.

Old names:

- `remote`, `transfer`, `mac`, `service`, `debug`, `quiet`, `pairing` are
  presets or compatibility names;
- they are not separate Bluetooth identities;
- `transfer` should normalize to router/session behavior.

## Expected First Pairing Sequence

```text
1. Boot
   - Classic hardware initialized.
   - Classic connectable=false, discoverable=false.
   - If no bond and pairing not armed: silent.

2. User selects Add Bluetooth Device
   - pairing_armed=true.
   - current connections may be disconnected deliberately.
   - BLE general advertising starts with one name.
   - Classic hardware is available for CTKD but classic discoverable stays false.

3. iPhone pairs once over BLE
   - SC Just Works, bonding=true.
   - Key distribution includes ENC, ID, LINK_KEY.
   - LE LTK/IRK and BR/EDR link-key are stored in one keystore session.

4. Runtime phase becomes both_bonded_transfer_idle
   - BLE advertising becomes directed/sticky or silent.
   - Classic connectable=false until Transfer activation.
   - iPhone should not see a second new device.
```

If an old bond predates CTKD/link-key distribution, it must be forgotten and
paired again once.

## Expected Transfer Activation

```text
1. User long-taps/explicitly connects route in Routes view.
2. Runtime starts/arms session graph.
3. Classic connectable=true, discoverable=false.
4. iPhone can connect A2DP using existing CTKD-derived Classic key.
5. Car Thing connects to selected trusted speaker.
6. Audio relay starts.
7. AMS/ANCS BLE service continues for metadata/control.
8. Speaker remote commands are normalized and sent back to iPhone over AMS.
9. Disconnect stops audio route, classic connectable=false, BLE control stays up.
```

## Negative Findings To Preserve

- Do not disable Classic hardware entirely in REMOTE: that breaks CTKD.
- Do not make Classic discoverable to solve speaker enrollment: Fosi is found by
  Car Thing inquiry; Car Thing itself should not advertise as a second device.
- Do not keep separate trusted source and trusted speaker databases as final
  architecture.
- Do not assume BLE filter policy hides advertising; undirected advertising
  still leaks name/appearance/services.
- Do not treat Classic link-key as proof of BLE reconnect readiness; AMS needs
  BLE LTK/IRK.
- Do not call one failed macOS USB probe proof that USB is absent.
- Do not declare BLE disconnected just because logs are quiet.
- Do not bake every runtime experiment into rootfs; preserve layer separation.
- Do not revive LVGL/web kiosk/BlueZ paths.
- Do not use direct raw `UDC` unbind scripts for USB storage.

## Deferred Ideas And Future Work

Release-adjacent:

- strict live proof for Fosi enrollment: authenticate/encrypt, link-key present,
  connected standby verified before persisting trusted device;
- multi-speaker selection model;
- explicit transition table:
  `from_session -> to_session -> action_before -> route_change -> action_after`;
- Lost Contact placeholder when BT disconnects;
- sticky reconnect refresh after new bond without requiring reboot;
- graceful runtime restart with explicit DRM/A2DP/BLE release instead of
  `os._exit(75)`;
- nonblocking system menu subprocess calls;
- route planner expansion for full-duplex and exclusive HCI/profile conflicts.

Audio/USB:

- UAC2 bridge with ALSA;
- T9015 playback live verification and unmute path;
- PDM 4-channel layout;
- USB HID/ACM/Mass Storage/MIDI profile expansion;
- USB disk guard screen and switch-back workflow;
- USB audio sample-rate anomaly investigation.

Research:

- iAP2 app-launch / NowPlaying narrowing;
- HFP call-state / microphone path;
- PBAP;
- CarPlay;
- MFi auth chip direct use;
- proximity/RSSI UX;
- contextual boot;
- TMD2772/LIS2DH12 feature usage;
- rootfs service cartridge with docs/tools/rollback helpers.

## Immediate Implementation Checklist

Before another live pairing attempt:

1. Ensure only the intended current runtime is deployed.
2. Ensure visible name is efuse-derived everywhere.
3. Clear stale Fosi/iPhone entries only when deliberately re-enrolling.
4. For iPhone CTKD proof, start from clean iPhone "Forget This Device" and
   clean Car Thing keystore.
5. Pair once through Add Bluetooth Device.
6. Verify stored keys contain LE LTK/IRK and Classic link-key.
7. Verify idle phase is `both_bonded_transfer_idle`.
8. Verify Classic `connectable=false`, `discoverable=false` in REMOTE.
9. Verify iPhone does not show a second Car Thing device.
10. Activate Transfer deliberately.
11. Verify Classic A2DP connects without a second pairing dialog.
12. Verify Fosi route connects only after strict successful enrollment.
13. Verify AMS metadata/control continues while audio routes through Fosi.
14. Verify deactivation returns to quiet Classic without losing BLE control.

## Verification Performed In This Recovery Pass

Local command:

```sh
cd (local repo root)
python3 scripts/smoke-route-graph.py
```

Result:

```text
ROUTE GRAPH SMOKE OK
```

This verifies current local route graph mechanics only. It does not verify live
Bluetooth radio behavior, CTKD on the actual iPhone, Fosi encryption/auth, or
audio relay.
