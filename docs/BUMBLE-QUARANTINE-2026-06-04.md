# Bumble Quarantine

Date: 2026-06-04

This release tree intentionally keeps the old Bumble-based runtime and lab tools
on disk, but disables their automatic startup.

Reason:
- the Bumble runtime proved useful for diagnostics;
- live iPhone dual-mode tests showed that it can create extra visible Bluetooth
  surfaces and failed BR/EDR authentication after BLE pairing;
- the release architecture now needs a lower, single Bluetooth owner instead of
  several scripts that can independently seize HCI.

Quarantine rules:
- `/etc/default/carthing` sets `CARTHING_BUMBLE_QUARANTINE=1`;
- `/etc/default/carthing` sets `CARTHING_ALLOW_BUMBLE_RUN=0`;
- the boot script was renamed from `S50-carthing-remote` to
  `:S50-carthing-remote.disabled`, so `rcS` will not auto-run it;
- `init-wrapper` skips the runtime while quarantine is enabled;
- `run-media-remote`, `tools/run_local.sh`, `tools/run_local_main.py`,
  `tools/hci_proxy.py`, and the Fosi standalone tests refuse to run unless the
  lab override is explicit.

Manual lab override:

```sh
CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 ./tools/run_local.sh
```

On the device, the old boot service is intentionally stored under the poisoned
name:

```sh
/etc/init.d/:S50-carthing-remote.disabled
```

Do not restore the old `S50-carthing-remote` name in a release image. That would
let the legacy runtime own HCI again during boot.
