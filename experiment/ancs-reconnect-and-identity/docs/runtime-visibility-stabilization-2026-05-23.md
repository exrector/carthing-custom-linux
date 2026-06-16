# Runtime visibility stabilization — 2026-05-23

## Problem

After power cycling and transfer-mode experiments, iOS/macOS could see two Car Thing Bluetooth surfaces:

- BLE HID/AMS media remote;
- classic A2DP audio endpoint.

The runtime was also trying to connect to the trusted speaker repeatedly even though `/etc/default/carthing` had `CARTHING_A2DP_AUTOCONNECT=0`.

## Cause

`run-media-remote` sourced `/etc/default/carthing`, but did not export the A2DP/trusted-device variables. Python therefore used code defaults:

- `CARTHING_A2DP_BRIDGE_ENABLE` defaulted to enabled;
- `CARTHING_A2DP_AUTOCONNECT` defaulted to enabled;
- `trusted-devices.json` supplied `Fosi Audio ZD3` as the default speaker.

When the A2DP bridge starts, it installs AudioSource/AudioSink SDP records and classic inquiry response data. This creates a second classic-audio identity next to the BLE media-remote identity.

## Current Product Rule

Default boot mode is media remote only.

Transfer/A2DP must not be enabled at boot until it has a controlled mode switch from the UI. This keeps the visible product surface stable and avoids background speaker connection attempts.

## Fix

- `/etc/default/carthing`: set `CARTHING_A2DP_BRIDGE_ENABLE=0`.
- `/usr/libexec/carthing/run-media-remote`: export A2DP and trusted-device variables so config is authoritative.
- `/etc/init.d/S50-carthing-remote`: supervise `media_remote.py`; if opening `hci-socket:0` fails with a transient busy error during boot, retry instead of leaving runtime down.

## Verified Live State

On device `172.16.42.77`:

- one `python3 /usr/lib/carthing/media_remote.py`;
- env contains `CARTHING_A2DP_BRIDGE_ENABLE=0` and `CARTHING_A2DP_AUTOCONNECT=0`;
- log has no A2DP receiver/autoconnect lines after restart;
- runtime starts directed reconnect to the bonded iPhone only.

## Persistent Artifact

Updated enlarged rootfs image:

- `artifacts/flash-device1-stabilize-visibility-20260523/rootfs.img`
- size: 512M
- sha256: `6801a02a390a9eeea71b310997f2d9e4bd3e299be19983b4b92769646b3d857b`

This image is derived from `artifacts/flash-device1-factory-name-20260522/rootfs.img`, not from older small rootfs images.
