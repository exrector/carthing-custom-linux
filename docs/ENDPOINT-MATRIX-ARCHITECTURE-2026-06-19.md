# Endpoint Matrix Architecture — 2026-06-19

## Decision

Car Thing route architecture uses a graph model:

```text
Device -> Endpoint/Node -> Route/Link
```

`Device` is only the physical/container object: Bluetooth address, display name,
bond/pairing state, connection state, and capability evidence. A `Device` is not
directly placed in the commutation matrix.

The matrix contains `Endpoint`/`Node` rows. Each endpoint has:

- `direction`: `source` or `sink`
- `plane`: `audio`, `control`, `metadata`, `session`, `mic`, or `usb`
- `protocols`: transport/profile choices, for example `classic_a2dp_sink`,
  `classic_a2dp_source`, `ble_l2cap_coc_session`, or `usb_ncm_session`
- `capabilities`: product-level meaning, for example `audio_input`,
  `audio_output`, `session_peer`, `remote_mic_receiver`, `playnow_metadata`,
  `usb_peer`

`Route`/`Link` always connects:

```text
source endpoint -> sink endpoint
```

Compatibility aliases may still expose `route_input` and `route_output` to older
UI/runtime code, but the internal route object carries `source_device_id`,
`source_endpoint_id`, `sink_device_id`, and `sink_endpoint_id`.

## Unified Device Intake

Every discovered peer enters the system through the same enrollment pipeline:

```text
physical peer -> evidence package -> Device card -> Endpoint rows -> usage hints
```

The evidence package is deliberately broader than the immediate route use case.
It should collect everything known at acquaintance time:

- Bluetooth identity: address, display name, class of device, bond/pairing state
- Classic SDP evidence: audio source/sink records, AVRCP, vendor records
- BLE/GATT evidence: AMS, ANCS, HID, CTSP bootstrap, other advertised services
- Session evidence: client/server capability, CoC/CTSP availability,
  `client_enabled` eligibility
- Microphone evidence: local mic source, remote mic receiver, format limits
- USB evidence: USB identity, NCM/session availability, USB audio capability
- Missing/unknown evidence: probes that failed, were skipped, or need retry

The registry writes one `Device` card for that physical peer regardless of
whether the user originally opened an "add speaker", "add source", "add Mac", or
"add USB" flow. Those flows are only discovery affordances.

After the card is written, `capability_profile.usage_hints` classifies how the
device can be used: `audio_source`, `audio_sink`, `session_peer`, `mic_source`,
`mic_sink`, `usb_peer`, `metadata_surface`, and `playnow_surface`. UI sorting and
route suggestions must read these hints/endpoints instead of assuming a
role-specific device type.

## Trusted Peer Presence

Live stickiness is centralized separately from enrollment and routing:

```text
trusted transport event -> TrustedPeerPresence -> live availability snapshot
```

This layer is common for every trusted device. Fosi, iPhone, MacBook, USB hosts,
and future peers do not get separate "sticky" architectures. They all report the
same event vocabulary:

- `incoming_attach`
- `outgoing_attach`
- `bond_seen`
- `usb_seen`
- `session_seen`
- `standby_held`
- `route_active`
- `disconnect`
- `timeout`
- `unreachable`

The resulting live states are:

```text
known -> seen -> present_unrouted -> standby -> route_active
       \-> missing / unreachable
```

Presence does not scan, pair, enroll, or change routes. It only records live
evidence from transports that already happened. Policies differ by endpoint
plane:

- `audio/sink`: may receive speaker standby keepalive
- `audio/source` and `metadata`: may receive Play Now stickiness
- `session`: may receive client/server stickiness
- `usb`: may receive attached-transport availability

The Route Wizard uses the presence snapshot plus an on-demand trusted-device
refresh when the user opens a route-change flow. Passive trusted reattach remains
allowed outside the wizard because it is not discovery: an already trusted peer
came back by itself.

## Why

The old language treated physical devices as "inputs" or "outputs". That breaks
as soon as a peer is multi-role: MacBook, iPhone, another computer, Car Thing
itself, and USB can all expose several independent endpoints.

The adopted model follows the shape used by modern audio graphs:

- PipeWire: device/node/port/link plus a session-level endpoint abstraction.
- JACK: clients own ports; links connect compatible ports.
- GStreamer: elements expose source and sink pads with capabilities.
- Core Audio: hardware is abstracted separately from processing graph scopes.
- Bluetooth media stacks: physical device, media endpoint, and media transport
  are separate concepts.

Primary references used for this decision:

- PipeWire Objects Design:
  <https://docs.pipewire.org/page_objects_design.html>
- GStreamer pads and capabilities:
  <https://gstreamer.freedesktop.org/documentation/application-development/basics/pads.html>
- JACK port/connection API:
  <https://jackaudio.org/api/group__PortFunctions.html>
- Apple Core Audio Overview:
  <https://developer.apple.com/library/archive/documentation/MusicAudio/Conceptual/CoreAudioOverview/WhatisCoreAudio/WhatisCoreAudio.html>

## Required Self Device Width

Car Thing itself is a first-class device/container in the graph. It must expose
at least these endpoints:

```text
carthing:playnow-metadata-sink     sink   metadata
carthing:playnow-control-source    source control
carthing:ctsp-session-source       source session
carthing:ctsp-session-sink         sink   session
carthing:local-mic-source          source mic
carthing:remote-mic-sink           sink   mic
carthing:usb-session-source        source usb
carthing:usb-session-sink          sink   usb
```

`Play Now` is not an audio output. It is a metadata/control surface: it displays
current source information and emits control intents.

The macOS helper/server is a separate peer device with matching session
endpoints. The Car Thing <-> macOS client/server relationship is represented as
links between session source/sink endpoints in both directions, controlled by
`client_enabled`.

USB is explicitly bidirectional. It is represented as at least one source and one
sink endpoint, not as a single opaque "USB mode".

Microphones are modeled in the `mic` plane. A local microphone is a source; a
remote microphone receiver is a sink.

## Migration Rules

Legacy JSON endpoint directions are normalized on load:

- `input` -> `source`
- `output` -> `sink`
- `session`, `control`, `metadata` -> direction inferred from capabilities,
  while the legacy word becomes `plane`

New writes should use `source`/`sink` plus explicit `plane`.

Existing UI lists named `route_inputs` and `route_outputs` remain as
compatibility views while the matrix UI is migrated to `route_nodes`.
