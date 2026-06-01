# Userspace Rebuild Plan

Status: accepted direction, 2026-06-01.

The old userspace should not keep driving product architecture. Keep the proven
low-level adapters and replace the top-level mode/service ownership with virtual
sockets, plugs, cables, route planning, and a session runner.

## Keep As Connectors

These are useful as lower-level connectors or protocol adapters:

- Bumble device/HCI transport setup;
- identity service and efuse naming;
- BLE reconnect and pairing primitives;
- AMS/ANCS/CTS/HID protocol code;
- A2DP relay code from the working donor path;
- USB gadget/profile tools;
- DRM/input/render primitives;
- persistent state mount and state paths.

They must not own product routing decisions.

## Remove As Product Architecture

These concepts should not remain as the final control model:

- hard `device_mode` as the root product state;
- `Remote` / `Transfer` / `Mac` as mutually exclusive service worlds;
- separate persistent source/speaker stores;
- mode-specific scan/connect loops;
- transfer UI assuming one hardcoded source;
- any script/process that captures HCI/Bumble/USB state outside the session
  runner.

## New Topology

```text
TrustedDeviceRegistry
  -> EnrollmentManager
  -> LinkManager
  -> RoutePlanner
  -> SessionRunner
  -> AdapterConnectors
```

The UI talks to the planner/runner, not directly to Bluetooth profiles.

## Virtual Socket Model

The upper layer sees:

- sockets: available attachment points exposed by Car Thing or adapters;
- plugs: endpoint offers from trusted devices;
- cables: active route connections between a plug and a socket;
- sessions: saved graphs of cables plus constraints.

Examples:

- iPhone audio source plug -> Car Thing A2DP sink socket;
- Car Thing A2DP source plug -> Fosi audio output socket;
- Fosi remote control plug -> Car Thing control backchannel socket;
- iPhone metadata plug -> Car Thing UI metadata socket.

## Migration Order

1. Introduce virtual socket/session runner modules without touching live startup.
2. Add registry migration from legacy `sources/speakers` to one `devices` list.
3. Build an enrollment manager that writes capabilities/endpoints/constraints.
4. Replace Transfer screen with simple route builder: choose input, choose output.
5. Replace `device_mode` application with session start/stop.
6. Retire old mode screen and old TransferService ownership.
7. Bake into rootfs only after the session runner is live-verified.

