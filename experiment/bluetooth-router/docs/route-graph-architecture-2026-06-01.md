# Car Thing Route Graph Architecture

Status: accepted architecture pivot, 2026-06-01.

This replaces the product-level idea of hard runtime modes with an Audio
Hijack-like session graph. The old userspace terms `remote`, `transfer`, `mac`,
`service`, and `debug` are now presets or compatibility names, not the core
architecture.

## Product Model

Car Thing is a media router and control surface.

The base flow is:

```text
trusted device registry
  -> capabilities / endpoints / constraints
  -> route planner
  -> active session graph
  -> protocol adapters
```

The user should not choose Bluetooth profiles or implementation details. The
user chooses a resource and a destination. The system chooses the protocol path.

## One Source Of Truth

There is one trusted-device registry.

There are no separate persistent databases for Inputs and Outputs. Inputs and
Outputs are GUI views over the same registry, filtered by capabilities.

Each trusted device stores:

- identity: address, stable id, display name, vendor hints;
- pairing material status: BLE keys, Classic link keys, future USB identity;
- capabilities: source, sink, control producer, control target, metadata,
  notifications, volume, transport buttons;
- endpoints: concrete protocol surfaces such as BLE AMS, ANCS, A2DP source,
  A2DP sink, AVRCP, USB audio in/out;
- constraints: exclusive resources, full-duplex policy, stop-before-start rules,
  transport conflicts, role conflicts;
- runtime state: online, connected, idle, active route, last seen.

Legacy sections such as `sources` and `speakers` are compatibility views only.

## Enrollment

Adding a device is a heavy operation. Day-to-day routing should be simple
because enrollment already did the hard work.

Enrollment must:

- scan the device as deeply as the peer allows;
- read all visible services/profiles;
- pair/bond all supported transports that the peer permits;
- classify audio/control/metadata/notification capabilities;
- store constraints explicitly instead of hiding exceptions in ad hoc code;
- save the device only when it is ready for normal use, or save it as degraded
  with a clear missing capability.

Examples:

- Fosi ZD3 is an audio output and may also be a control producer through its
  remote/buttons.
- iPhone is a media/control/notification peer and can also be an audio source
  when an A2DP route is selected.
- Mac may be a source, sink, control peer, or a full-duplex candidate depending
  on endpoints and resource conflicts. This must be decided by constraints, not
  by a hardcoded rule.

## Link Layer

Trusted devices are hot inventory.

The link layer may keep a trusted peer attached or periodically probe it, but it
must not imply an active media route.

Idle connected means:

- keys are valid;
- peer is reachable or attached;
- no media traffic is flowing;
- no user-visible route is active unless a session requests it.

Traffic starts only when an active session graph selects endpoints and the
session runner starts protocol adapters.

## Session Graph

A session is a saved route graph. It can be started and stopped.

Presets are named sessions:

- Remote Media Control: control/metadata/notifications to the Car Thing UI;
- Transfer: selected input endpoint to selected output endpoint, plus optional
  control backchannel;
- Mac Control: Mac endpoint to UI/control surface;
- Service/Debug: diagnostic graphs.

Starting a new session must be deterministic:

```text
stop current session
release active routes and exclusive protocol resources
keep trusted idle links where allowed
plan new route graph
start required protocol adapters
publish runtime state
```

No reboot, no parallel script leftovers, no hidden second Bluetooth persona.

## Blocks

The internal graph is made of blocks:

- Device block: a trusted physical peer such as iPhone, Mac, Fosi;
- Endpoint block: an input/output/control endpoint on a device;
- Adapter block: BLE AMS, ANCS, A2DP sink, A2DP source, AVRCP, USB audio;
- Router block: switch, relay, future mixer, monitor;
- Control block: local controls, speaker remote backchannel, metadata route;
- Output block: audio sink, UI sink, recorder/debug sink.

The first implementation can expose a simple two-step GUI:

```text
choose input resource
choose output resource
planner builds the session
```

The block graph remains internal until the UI is ready for more advanced
editing.

## Constraints

Exceptions must be data, not scattered conditionals.

Useful constraints:

- `exclusive_resource:hci0`
- `exclusive_profile:a2dp_source`
- `exclusive_profile:a2dp_sink`
- `requires_stop_before_start`
- `full_duplex_allowed`
- `full_duplex_forbidden`
- `control_backchannel_only`
- `idle_link_allowed`
- `active_media_requires_user_route`

The planner may reject a route, stop a conflicting session, or select a lower
quality fallback based on these constraints.

## Userspace Rewrite Rule

The current userspace can be replaced if it fights this model.

Keep:

- identity service and efuse naming rule;
- persistent state mount;
- proven BLE reconnect pieces;
- GUI rendering primitives that still fit the one-surface UI;
- proven A2DP relay donor code where it works.

Replace or wrap:

- `device_mode` as a product concept;
- separate `trusted_sources` / `trusted_speakers` persistence;
- transfer-specific UI that assumes one hardcoded input;
- mode-specific scan/connect loops;
- any process/script that owns transport state outside the session runner.

Target modules:

- `trusted_device_registry.py`
- `enrollment_manager.py`
- `link_manager.py`
- `route_graph.py`
- `route_planner.py`
- `session_runner.py`
- protocol adapters for BLE, Classic A2DP, AVRCP, USB audio, UI/control.
