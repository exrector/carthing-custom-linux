# Preservation 2026-05-19

This directory is the durable handoff point for the late `2026-05-18` /
early `2026-05-19` BLE reconnect and clean-room iAP2 work.

## What Is Preserved Here

- `tmp/private-tmp/`
  - copied originals from scattered `/private/tmp` work areas
  - includes the iAP2 mini binaries, test binaries, MFi probe test binary,
    btattach livecheck files, fwload build files, and small one-off logs
- `tmp/tmp/`
  - copied originals from `/tmp` for the host and target `carthing-iap2-mini`
    test binaries
- `device-runtime/`
  - live device snapshot captured after the reconnect work
  - includes:
    - `keys.json`
    - `ps.txt`
    - `carthing-remote.tail.txt`
- `git/`
  - `HEAD.txt`
  - `git-log.txt`
  - `git-status.txt`
  - `carthing-custom-linux-master.bundle`
- `MANIFEST.txt`
  - size and SHA-256 for every preserved file in this directory

## Important State Boundary

- current repo `HEAD` contains the reconnect commits:
  - `0313c26` `Checkpoint add bonded-only BLE reconnect path`
  - `3f35243` `Checkpoint record 2-minute BLE reconnect proof`
- the later `~10 minute` airplane-mode reconnect proof is also recorded in docs
  and committed after this preservation pass
- the latest reconnect logic is preserved in source and in this artifact set
- but no new permanent `rootfs.img` was baked during this preservation pass

That means:

- source state is safe
- temp/original helper files are safe
- live runtime evidence is safe
- a future session can still choose whether to build/patch/flash a new rootfs
  from this preserved state

## Known Working User Facts At This Point

- cold boot reconnect works
- short Bluetooth toggle reconnect works
- about `2 minutes` disconnect reconnect works
- about `10 minutes` airplane-mode disconnect reconnect works
- pair reset after `Forget This Device` requires clearing device-side
  `keys.json` before expecting a clean pair

## Existing Release Baseline

The older flashed baseline bundle is still here:

- `artifacts/releases/device1-v1-working-20260518/bundle/`

This preservation directory does not replace that bundle. It extends it with
later reconnect-era source commits and scattered temporary originals that were
not yet folded into a new image.
