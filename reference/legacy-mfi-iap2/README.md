# Legacy MFi / iAP2 Reference Archive

This directory is a curated preservation snapshot from older local Car Thing repositories that are no longer part of the active `carthing-custom-linux` source tree.

Purpose:

- keep the useful MFi / iAP2 reverse-engineering notes
- keep one representative `slot_a` implementation snapshot
- keep one representative low-level integration file
- avoid keeping multi-gigabyte legacy trees just to preserve a few important files

What is preserved here:

- `docs/`
  - high-value notes and historical project maps
- `re/qt-superbird-app/`
  - extracted reverse-engineering text artifacts
- `slot_a/`
  - one representative implementation snapshot of the old iAP2 agent flow
- `device_root/`
  - small supporting files used by that old flow
- `kernel/`
  - one integration reference file showing how the Apple MFi kernel pieces were wired in

Primary source paths:

- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/MFI_IAP2_SPECIFICATION.md`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/SLOT_A_IAP2_AGENT_TASK.md`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/qt-superbird-app.re/`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/device_root/home/superbird/slot_a/`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/device_root/bin/`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/archiv/device_root/etc/`
- `~/Documents/ПРОЕКТЫ/CAR-THING/trash/nixos-superbird/modules/sys/kernel/mfi/apple-mfi.nix`
- `~/Documents/ПРОЕКТЫ/CAR-THING/carthing-media-remote/carthing-remote/PROJECT_STRUCTURE.md`
- `~/Documents/ПРОЕКТЫ/CAR-THING/carthing-media-remote/Вывод Терминала codex.txt`

Selection policy:

- prefer text, notes, code, and small config files
- avoid preserving duplicate multi-gigabyte archives
- keep only one canonical copy when the same file appeared in several legacy trees
