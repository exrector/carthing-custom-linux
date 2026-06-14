# Persistent state storage

Date: 2026-06-13

## Contract

`/run/carthing-state` must be a journaled Linux filesystem. It must not be the
FAT boot partition.

The Superbird boot ABI still expects the boot partition payload on
`/dev/mmcblk0p1`:

- `Image`
- `initrd`
- `superbird.dtb`

Therefore `/dev/mmcblk0p1` remains a boot partition and is mounted read-only as
`/run/carthing-boot`. Persistent runtime state moves to `/dev/mmcblk0p3`, mounted
as ext4 on `/run/carthing-state`.

## Why

The old layout mixed boot files and runtime state on `/dev/mmcblk0p1`:

- p1 partition type: FAT32 LBA
- mounted at `/run/carthing-state`
- contained both boot payload and `carthing/state.json`

That made `state.json` and Bluetooth keys dependent on FAT behavior during hard
USB power loss. Atomic temp+fsync+rename helps file-level writes, but it does
not turn FAT into a journaled persistent-state layer.

## Migration

Use the guarded host tool:

```sh
tools/carthing-migrate-state-to-p3-ext4
tools/carthing-migrate-state-to-p3-ext4 --apply
```

The tool validates the existing MBR layout before writing anything:

- p1: start `8192`, size `65536`, type `0x0c`
- p2: start `352256`, type `0x83`
- p3: empty

It creates p3 in the free aligned gap after p1 and before p2:

- start `73728`
- size `262144` sectors, 128 MiB
- type `0x83`

Then it streams a host-created ext4 image to `/dev/mmcblk0p3` and restores the
previous `carthing/` state directory from backup.

## Boot behavior

`S11-runtime-state` now fails loudly if `/run/carthing-state` is not ext4. It no
longer silently accepts vfat as the persistent-state backend.
