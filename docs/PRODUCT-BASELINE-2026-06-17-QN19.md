# Product baseline — QN19 — 2026-06-17

This document is the current source of truth for the product baseline after the
mixed-folder cleanup audit. It intentionally separates proven live facts from
future design work.

## Status

Baseline status: local image baseline repaired; device not reflashed in this
session after the latest mount/debug cleanup.

Device status: QN19 boots and runs the custom Buildroot runtime. The live
system is operational, but the local image/source tree needed cleanup because
some docs described reverted state-on-p2 work as if it were still installed.

No reboot, flash, repartition, or filesystem repair was performed during this
baseline audit. Later in the same cleanup pass, the live device was changed only
at the p1 state/debug layer: p1 state was backed up, macOS metadata files were
removed, debug profile was set to `quiet`, HTTP/telnet/reverse-agent were
stopped, and p1 was remounted with `noatime,nodiratime`.

## Partition architecture

Current product architecture uses only the two Linux-visible partitions:

| Partition | Filesystem | Current role |
|-----------|------------|--------------|
| `/dev/mmcblk0p1` | FAT32 | U-Boot-readable boot files plus small runtime state at `/run/carthing-state` |
| `/dev/mmcblk0p2` | ext4 | readonly Buildroot rootfs mounted as `/` |

Important decisions:

- p1 must remain FAT. U-Boot reads `Image`, `bootargs.txt`, and `superbird.dtb`
  from it.
- p2 remains the reproducible rootfs image. It is not the writable state store
  in the current product baseline.
- p3 is not part of the product architecture. Treat prior p3 work as
  research/rejected unless it is explicitly reopened.
- The reverted `6358ad9` state-on-p2 commit is not current behavior. Current
  live and source state use p1/vfat for `/run/carthing-state`.

Crash-safety policy for the current baseline:

- persistent writes must stay rare;
- runtime metadata belongs in tmpfs under `/run/carthing`;
- `state.json` must use atomic write plus backup/recovery;
- avoid rebooting after p1 writes unless p1 has been synced and its state is
  understood.

## Live QN19 facts

Observed live on 2026-06-17:

- OS: Buildroot `2026.02.1-dirty`
- init: BusyBox init
- kernel: Linux `4.9.113`
- `/` mounted from `/dev/mmcblk0p2` as ext4 readonly
- `/run/carthing-state` mounted from `/dev/mmcblk0p1` as vfat
- after live cleanup and FAT state-byte fix: `/run/carthing-state` mounted as
  vfat with `noatime,nodiratime,flush,errors=remount-ro`
- USB NCM product string: `Exrector QN19`
- runtime: `/usr/lib/carthing/carthing_runtime.py`
- Bluetooth attach path: `carthing-btattach-mini`
- Python: `3.14.4`
- no on-device compiler/toolchain
- `/dev/ge2d` exists on the live device
- iPhone BLE/AMS/ANCS/CTS path was live during the audit

Resolved during the 2026-06-17 cleanup: an intermediate bootfs had Linux FAT16
state byte `0x25` set to `0x01`, so the kernel logged this on every boot:

```text
FAT-fs (mmcblk0p1): Volume was not properly unmounted. Some data may be corrupt. Please run fsck.
```

The canonical bootfs now clears that byte to `0x00` before flashing
(`6e99a75c...`). Live QN19 was patched the same way, rebooted, and
`dmesg | grep -i FAT-fs` returned no warning. While the partition is mounted RW,
Linux sets byte `0x25` back to `0x01`; that is expected mount-state behavior and
must be cleared again by clean remount-ro/unmount.

Follow-up bootargs cleanup also removed vendor Android parameters from p1
`bootargs.txt`: `reboot_mode_android`, `androidboot.*`, `jtag`, and
`uboot_version`. Live QN19 rebooted with a clean `/proc/cmdline` and no FAT
warning.

## Image/source reconciliation

Before this cleanup:

- `image/rootfs.img` matched most baked runtime files on QN19, but did not
  include hot-deployed `ge2d.py` / `ge2d_test.py`.
- current `overlay/` had files that were not present in `image/rootfs.img` or
  live rootfs.
- bake did not include native AAC/SBC libraries even though the runtime can
  enable AAC-to-SBC transcode.

After this cleanup:

- `tools/bake-rootfs.py` bakes `ge2d.py`, `ge2d_test.py`, `libhelixaac.so`,
  `libsbc.so`, and `sbc_synth.so`;
- `image/rootfs.img` was updated locally;
- `image/SHA256SUMS` records rootfs sha256 `1084cbc6...`;
- the previous rootfs was preserved at
  `image/archive-20260617-123635/rootfs-before-clean-baseline.img`;
- QN19 was not flashed or rebooted.

After the follow-up cleanup:

- `source/base-bundle/bootfs.bin` was synchronized to the current clean GE2D bootfs
  sha256 `6e99a75c...`;
- `tools/bake-rootfs.py` rejects the old known-bad bootfs sha256 `7977c311...`
  and the dirty-FAT bootfs sha256 `2ff2159a...`, intermediate dirty-state
  bootfs sha256 `28f4b24a...`, and Android-bootargs bootfs sha256
  `957f91c3...`;
- `image/rootfs.img` was rebuilt again with sha256 `1084cbc6...`;
- baked rootfs has only `S03-runtime-state`; retired duplicate
  `S11-runtime-state` is absent;
- baked release defaults set debug profile to `quiet`, disabling HTTP, telnet,
  and reverse-agent by default.

Required baseline rule:

- `overlay/` is the source for the next rootfs bake;
- `image/rootfs.img` is the flashable product image;
- hot-deploys are temporary only and must be either baked or removed;
- every rootfs bake must produce a bundle manifest and `image/SHA256SUMS`.

## Build/flash contract

Normal product work:

1. edit files under `overlay/`;
2. run `python3 tools/bake-rootfs.py`;
3. copy the baked `rootfs.img` into `image/rootfs.img`;
4. update `image/SHA256SUMS`;
5. flash only after explicit decision.

Kernel work is separate:

- current kernel was built with GCC 6.5.0 in a NixOS/Colima-style builder;
- `#1-NixOS` in `uname -a` is a kernel build string, not the installed OS;
- kernel provenance is incomplete until the exact config, command, toolchain,
  and artifact hashes are captured next to the GE2D kernel artifact.

## Not part of the product baseline

- p3 state partition;
- converting p1 from FAT to ext4;
- resizing p2 online;
- real Linux `poweroff`/`halt`;
- folder sprawl as an active development model.

The GUI `Отключение USB -> Подготовить` action is allowed and intentional: it is
the product path for preparing physical USB power removal. It stops runtime
activity, syncs state, makes `/run/carthing-state` clean/read-only or unmounted,
blanks the screen, and enters suspend. It is not Linux `poweroff`/`halt`.

Large historical folders may remain physically present as archives, but the
active project root is this repository's top-level `overlay/`, `tools/`,
`scripts/`, `image/`, `source/base-bundle/`, and current `docs/`.
