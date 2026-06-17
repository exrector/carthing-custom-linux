# Repository cleanup — 2026-06-17

This is the cleanup ledger for `carthing-release-integration`. It exists so the
project can be cleaned without losing history or confusing archive material with
the product baseline.

## Active product surface

| Path | Status | Reason |
|------|--------|--------|
| `overlay/` | active source | source for the next rootfs bake |
| `tools/bake-rootfs.py` | active build tool | canonical rootfs bake path |
| `tools/flash.py` | active flash tool | canonical full image flash path |
| `scripts/bring-up-device1-normal-boot-macos.sh` | active host tool | canonical macOS NCM route repair |
| `scripts/check-device1-normal-boot-macos.sh` | active host tool | canonical normal-boot diagnostic |
| `image/` | active flash bundle | gitignored binaries plus tracked hashes/docs |
| `source/base-bundle/` | active base input | Buildroot baseline used by bake |
| `docs/PRODUCT-BASELINE-2026-06-17-QN19.md` | active doctrine | current P1/P2 product baseline |

## Archive/reference surface

| Path | Status | Handling |
|------|--------|----------|
| `carthing-device-backups/` | archive | keep for restore/provenance; not active source |
| `carthing-custom-linux/` | archive/imported history | keep outside active source decisions |
| `carthing-release-architecture/` | architecture reference | mine for ideas only; not product code |
| `experiment/` | lab/reference | not baked unless explicitly promoted |
| `reference/` | curated reference | not runtime |
| `native/` | native source/artifacts | source/provenance for copied runtime `.so` files |

## Current cleanup findings

| Finding | Status | Action |
|---------|--------|--------|
| `overlay/__pycache__` and `.pyc` files | generated noise | remove locally; already ignored |
| `overlay/usr/lib/carthing/media_remote.py` | retired runtime | removed from active overlay; history remains in git and archive docs |
| `overlay/usr/lib/carthing/libhelixaac.so` | native runtime dependency | keep and bake into rootfs |
| `overlay/usr/lib/carthing/libsbc.so` | native runtime dependency | keep and bake into rootfs |
| `overlay/usr/lib/carthing/sbc_synth.so` | native decoder accelerator | keep and bake into rootfs |
| `ПЛАН-ПРИОРИТЕТЫ.md` p2-state DONE claims | stale/reverted | correct to current p1/vfat + backup-recovery baseline |
| `INVARIANTS.md` p2-state DONE claim | stale/reverted | correct to current p1/vfat + rejected p3 |
| GE2D kernel artifact without build log/config | provenance gap | document as working live, not fully reproducible yet |
| `source/base-bundle/bootfs.bin` had old sha `7977c311...`, then dirty-FAT GE2D sha `2ff2159a...`, then intermediate sha `28f4b24a...` | dangerous stale/dirty binary | replaced with clean GE2D bootfs `957f91c3...`; bake now rejects `7977c311...`, `2ff2159a...`, and `28f4b24a...` |
| duplicate `S11-runtime-state` | confusing duplicate mount path | removed from overlay and retired by bake |
| debug HTTP/telnet/reverse-agent on by default | product security risk | release default is now `quiet`; live QN19 ports left with SSH only |
| macOS `._*` / `.fseventsd` files on live p1 | generated boot-partition noise | removed live after p1 backup |

## Deletion policy

Delete immediately:

- generated `__pycache__/`;
- `*.pyc`;
- `.DS_Store`;
- `._*`.

Do not delete without a manifest:

- device backups;
- nested historical repos;
- flash images;
- kernel artifacts;
- reverse-engineering references.

Do not treat archive folders as active source. If a file from an archive is
needed, promote it into the active surface with a commit and a note in this
ledger.
