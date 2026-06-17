# Boot profiling

This project treats boot-speed work as an evidence task, not as a boot-chain
replacement by default.

## Current production baseline

QN19 currently uses the P1/P2 layout:

- p1 `/dev/mmcblk0p1`: FAT, U-Boot-readable `Image`, `superbird.dtb`,
  `bootargs.txt`, plus small runtime state at `/run/carthing-state`.
- p2 `/dev/mmcblk0p2`: readonly ext4 Buildroot rootfs mounted as `/`.
- The runtime starter is intentionally named `disabled-S50-carthing-remote`,
  but it is active: `init-wrapper` calls it by name after the early rescue
  services are up.

Do not replace this with GPT/P3/new U-Boot as a cleanup step. Those are separate
research paths and need their own recovery plan.

## Collect a profile

With the device booted normally and reachable over USB/NCM:

```sh
./tools/boot-profile.sh --host carthing
```

The script is read-only. It collects:

- kernel/init timing from `dmesg`;
- p1/p2/mount state;
- `/run/carthing/init-wrapper.log`;
- runtime `BOOT_PROFILE` milestones from `/run/carthing/carthing-remote.log`;
- process and `/run/carthing` state.

If `BOOT_PROFILE` lines are absent, the live rootfs predates this profiling
instrumentation. Rebuild/flash or deploy the updated runtime before comparing
Python GUI/Bluetooth startup timing.

## Runtime milestones

`overlay/usr/lib/carthing/carthing_runtime.py` emits lines like:

```text
BOOT_PROFILE milestone=gui.display_ready proc_uptime_s=14.321 runtime_s=7.100 kind=drm
```

`proc_uptime_s` is seconds since kernel start on the device. `runtime_s` is
seconds since the Python runtime module loaded.

Disable this small amount of logging with:

```sh
CARTHING_BOOT_PROFILE=0
```

## Upstream boot-chain research

`ThingLabsOSS/superbird-uboot` and `ThingLabsOSS/superbird-fip-tools` are useful
research inputs because they target a Spotify-free boot chain and claim fast
cold boot to panel splash. They are also high-impact: flashing them changes the
eMMC boot0/boot1 path and can wipe/terraform the user area.

For this project the safe order is:

1. Capture current boot profiles on the product baseline.
2. Build and RAM-boot upstream U-Boot/FIP on a research branch or throwaway
   device session first.
3. Compare cold-boot-to-splash, SSH-ready, runtime-ready, and GUI-ready timings.
4. Only then decide whether replacing the boot chain is worth the migration and
   recovery complexity.
