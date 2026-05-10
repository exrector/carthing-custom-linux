# Storage Map And Cleanup

This file answers three questions:

1. what is the current source of truth
2. what is generated and reproducible
3. what is safe to delete now if disk space matters

## Source Of Truth

These paths are the real project and should be kept:

- `README.md`
- `docs/`
- `buildroot-external/`
- `overlay/`
- `scripts/`
- `artifacts/flash-device1/`
- `reference/legacy-mfi-iap2/`

Notes:

- `artifacts/flash-device1/` is the active flash bundle for device `№1`
- the active `rootfs.img` currently has SHA-256:
  - `fc19290a025ce9a7794c421dc297f05ac5a5db50cb28b114fed6fb64f141c72d`
- `bootfs.bin` and `env.txt` inside that bundle are part of the reused boot contract and should stay with the active bundle

## Generated Inside This Repo

These paths are reproducible and not authoritative:

- `host-tools/`
  - project-local GNU/macOS helper tools for Buildroot
  - safe to delete, but they will need to be rebuilt or reinstalled
- `distfiles/`
  - cached source tarballs
  - safe to delete, but downloads will be needed again
- `scripts/__pycache__/`
  - Python bytecode cache
  - safe to delete

## Temporary / Experimental Inside This Repo

These paths are not source of truth:

- `artifacts/flash-device1-buildroot-control/`
  - one-off control bundle built from the old preserved Buildroot artifact
  - used only to test whether the historical `rootfs.ext2` reproduced the old `.77` behavior
  - not the active bundle
  - safe to delete

## Generated Outside This Repo

These paths are large and reproducible:

- `/Volumes/carthing-buildroot-case/output-carthing/build`
  - about `11G`
  - Buildroot package build tree
  - safe to delete if you accept losing incremental build state
- `/Volumes/carthing-buildroot-case/output-carthing/host`
  - about `1.2G`
  - Buildroot host tools and toolchain outputs
  - safe to delete if you accept rebuilding host tools later
- `/Volumes/carthing-buildroot-case/output-carthing/target`
  - about `52M`
  - staged target rootfs tree
  - safe to delete
- `/Volumes/carthing-buildroot-case/output-carthing/images`
  - about `60M`
  - Buildroot-generated image outputs
  - safe to delete if the active flash bundle already contains what you need

## Historical Repos Outside This Repo

These are not part of the current custom-linux source of truth:

- `~/Documents/ПРОЕКТЫ/CAR-THING/carthing-media-remote`
  - about `9.0G`
  - major heavy items:
    - `carthing-remote/` about `6.4G`
    - `архив.zip` about `2.5G`
- `~/Documents/ПРОЕКТЫ/carthing-nixos`
  - about `1.7G`
  - almost all weight is `_prebuilt/`

The important MFi / iAP2 archaeology has been curated into `reference/legacy-mfi-iap2/`.
After that preservation step, these old repos are no longer required by the current project.

## Safe To Delete Now

These are the safest immediate deletions:

- `artifacts/flash-device1-buildroot-control/`
- `scripts/__pycache__/`
- any temporary `/tmp` extraction or comparison folders created during debugging
- detached temporary disk-image attachments created only for inspection

## Safe To Delete For Space, With Rebuild Cost

These are also safe, but they trade space for rebuild time:

- `host-tools/`
- `distfiles/`
- `/Volumes/carthing-buildroot-case/output-carthing/build`
- `/Volumes/carthing-buildroot-case/output-carthing/host`
- `/Volumes/carthing-buildroot-case/output-carthing/target`
- `/Volumes/carthing-buildroot-case/output-carthing/images`

## Current Recommendation

If the goal is to free space without losing the current project state:

1. keep the repo itself and `artifacts/flash-device1/`
2. delete `artifacts/flash-device1-buildroot-control/`
3. delete `scripts/__pycache__/`
4. then decide whether to keep or delete `/Volumes/carthing-buildroot-case/output-carthing/build` and `host`

That one Buildroot output tree is the main local storage consumer in the current custom-linux workflow.
