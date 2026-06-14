# Capability/Profile Architecture - 2026-05-25

## Principle

The release architecture must avoid rebuilding or reflashing for every hardware experiment.

Kernel, DTB, and rootfs should expose a broad but conservative capability set. Runtime services and the GUI should decide which capabilities are active.

Default boot must stay boring:

- USB NCM for access/recovery.
- SSH/debug access according to `/etc/default/carthing`.
- Media remote runtime only if enabled.
- No optional USB/Bluetooth/audio/sensor modes activated just because the driver exists.

## Layers

### Kernel/DTB

Purpose: make hardware and protocol functions available.

Examples:

- USB gadget configfs functions: NCM, ECM, RNDIS, EEM, ACM/serial, Mass Storage, UAC1/UAC2, MIDI, HID.
- Audio hardware path: T9015 playback/capture, PDM capture.
- Input: touch, buttons, encoder, uinput.
- I2C userspace access for MAX20332, MFi chip, sensors that are physically present.
- Thermal zones and safe hardware inventory.

Kernel/DTB should not encode product mode policy. They should expose capability.

### Early Runtime

Purpose: create stable access and protect recovery.

Default:

- USB profile `ncm`.
- NCM is mandatory.
- Optional USB functions are inactive until explicitly selected.
- If configfs setup fails, try the legacy `g_ncm` module as a fallback.

### Profile Managers

Purpose: switch active capabilities without flashing.

Current first manager:

- `/usr/libexec/carthing/usb-profile`
- `/usr/libexec/carthing/profilectl`
- `/usr/libexec/carthing/bt-profile`
- `/usr/libexec/carthing/audio-profile`
- `/usr/libexec/carthing/sensor-profile`
- `/usr/libexec/carthing/debug-profile`
- state file: `/run/carthing/usb-gadget-profile`
- default profile: `ncm`

Planned sibling managers:

- Bluetooth profile manager: remote control, audio source/sink/bridge, pairing, trusted-device roles.
- Audio profile manager: internal playback, USB gadget audio, Bluetooth bridge, microphone capture.
- Sensor profile manager: poll/interrupt modes for light/proximity, thermal, input, motion if physically present.
- Debug profile manager: HTTP, telnet, reverse agent, verbose logging.

### GUI

Purpose: present settings and mode choices.

GUI must not directly know low-level scripts. It should request profile changes through manager commands and read manager state.

Example:

```sh
/usr/libexec/carthing/usb-profile set ncm,audio
/usr/libexec/carthing/usb-profile set ncm
```

The profile layer is now shared across domains:

```sh
/usr/libexec/carthing/profilectl status
/usr/libexec/carthing/profilectl usb set ncm,audio
/usr/libexec/carthing/profilectl bt set transfer
/usr/libexec/carthing/profilectl audio set bridge
/usr/libexec/carthing/profilectl sensor set full
/usr/libexec/carthing/profilectl debug set service
```

Persistent profile choices live under `/run/carthing-state/carthing/profiles`.
Runtime env projections live under `/run/carthing/*.env` and may disappear on
reboot; they are regenerated during boot by `S03-runtime-state`.

## USB Contract

Default boot profile:

- `ncm`

Optional USB profile tokens:

- `audio`
- `serial`
- `hid`
- `midi`
- `storage`
- `ecm`
- `eem`
- `rndis`

Profiles are comma-separated and always keep NCM unless a future profile manager explicitly supports a recovery-safe exception.

Examples:

- `ncm,audio`
- `ncm,serial`
- `ncm,audio,serial,hid,midi`

## Release Rule

A new capability should be added in this order:

1. Enable driver/function availability in kernel/rootfs.
2. Keep it inactive by default.
3. Add a profile-manager command.
4. Add GUI control.
5. Test activation/deactivation without reflashing.

Reflashing is for changing the capability substrate. It is not for toggling product modes.
