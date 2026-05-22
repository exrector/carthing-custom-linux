# Car Thing factory identity — source of truth (2026-05-22)

This is a hard project rule for future agents.

## Rule

The user-visible Car Thing name must come from the manufacture efuse USID first.

On the verified device:

```text
/sys/class/efuse/usid = 8559RP88Q917
serial suffix         = Q917
device name           = Car Thing (SN: Q917)
```

That name is the single source of truth for:

- OS hostname
- Bumble `Device.name`
- controller local name
- BLE advertising when pairing/discoverability is explicitly open
- classic inquiry response name
- A2DP bridge name
- GUI pairing text and runtime state
- logs and handoff diagnostics

The controller MAC is not the primary user-visible identity. MAC-derived names
are allowed only as last-resort fallback when efuse/config/hostname are missing.

## Implementation

Primary implementation points:

- `overlay/usr/lib/carthing/runtime_paths.py`
  - `manufacturing_serial()`
  - `factory_device_name()`
  - `device_name()`
- `overlay/etc/init.d/S04-hostname`
  - sets the OS hostname from efuse before Python runtime starts
- `overlay/etc/init.d/S25-bt-metadata`
  - writes metadata/settings from the same derived name
- `overlay/usr/lib/carthing/ble_transport.py`
  - sets Bumble `Device.name`
  - writes controller local name after `power_on()`
- `overlay/usr/lib/carthing/media_remote.py`
  - `bluetooth_name()` reads the initialized device name and falls back to `device_name()`
- `overlay/usr/lib/carthing/a2dp_bridge.py`
  - uses the unified name; no separate "audio" alias

Config variables are fallback/configuration only:

```sh
CARTHING_FACTORY_NAME_PREFIX="Car Thing"
CARTHING_EFUSE_USID_PATH=/sys/class/efuse/usid
CARTHING_NAME_BASE=CarThing
```

Do not hardcode `Q917` into config. `Q917` is derived from efuse.

## Verified persistent image

Commit:

```text
98d6a85 Use factory efuse name across Bluetooth runtime
```

Persistent rootfs image flashed on 2026-05-22:

```text
artifacts/flash-device1-factory-name-20260522/rootfs.img
size:   512M
sha256: e8b494b3bea92c60640311fa1cfd1e44b37cc55e95bf1876d2f7315ece4f13ce
```

The image was built from the intentionally enlarged 512M
`artifacts/flash-device1-attach/rootfs.img`, not from older 60M images.

Verification after reboot:

```text
hostname: Car Thing (SN: Q917)
runtime:  python3 /usr/lib/carthing/media_remote.py
log:      Controller public address: 30:E3:D6:04:C3:42 -> name=Car Thing (SN: Q917)
log:      BLE device ON ... name: Car Thing (SN: Q917)
log:      A2DP bridge started ... name=Car Thing (SN: Q917)
```

## Do not regress

Do not reintroduce:

- `CarThing-<MAC>` as the normal visible name
- `Car Thing Audio` as a separate A2DP-visible name
- hardcoded serials in default config
- separate per-layer naming logic

If another physical unit is used, read its own `/sys/class/efuse/usid` and let
the same code derive its own `Car Thing (SN: XXXX)` name.
