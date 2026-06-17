# PENDING-BAKE — что нужно запечь в следующий образ

Сюда пишем всё что изменено на живом устройстве вручную и ещё не запечено в rootfs.img.
Перед каждым бейком — пройтись по списку и убедиться что всё внесено в overlay.

---

## Ожидает бейка

*(пусто после локального bake `flash-bake-unified-stable-20260618-015815`; устройство не прошивалось этим bundle)*

---

## Запечено (история)

| Дата | Что изменено | Как запечено |
|------|-------------|--------------|
| 2026-06-17 | GE2D userspace (`ge2d.py`, `ge2d_test.py`) + native AAC/SBC libs (`libhelixaac.so`, `libsbc.so`, `sbc_synth.so`) | `tools/bake-rootfs.py` → `image/rootfs.img`, then sha256 `13b2b14f...` |
| 2026-06-17 | Product mount/debug cleanup: `S03-runtime-state` only, vfat `noatime,nodiratime,flush`, release debug profile `quiet`, HTTP/telnet/reverse-agent off by default | `tools/bake-rootfs.py` → `image/rootfs.img`, then sha256 `13b2b14f...` |
| 2026-06-17 | Boot profiling markers + precompiled Python bytecode (`342` `.pyc` files) + ранний DRM/GUI home surface перед BLE/Bumble init | `tools/bake-rootfs.py` → `image/rootfs.img`, latest sha256 `b638d769...` |
| 2026-06-17 | `source/base-bundle` hardware baseline repaired: old bootfs `7977c311...`, dirty-FAT GE2D bootfs `2ff2159a...`, intermediate bootfs `28f4b24a...`, and Android-bootargs GE2D bootfs `957f91c3...` replaced with clean Linux/CarThing bootfs `6e99a75c...`; bake rejects all stale hashes | `source/base-bundle/SHA256SUMS` + `tools/bake-rootfs.py` guard |
| 2026-06-17 | Ядро с GE2D (`CONFIG_AMLOGIC_MEDIA_GE2D=y`) — `/dev/ge2d` теперь есть; `bootargs.txt` cleaned from Android/vendor params | `image/bootfs.bin` обновлён и FAT-cleaned, sha256 `6e99a75c` |
| 2026-06-17 | Пароль root = `carthing` | `overlay/etc/shadow` создан с SHA-512 хэшем; `bake-rootfs.py` копирует его автоматически |
| 2026-06-17 | Логотип при загрузке — наш (вождь, 480×800 RGB565), normal boot slot `bootup_spotify` | `image/bootlogos.bin` + `tools/flash.py` пишет в сектор 319488 при прошивке |
| 2026-06-17 | BT-бонды не переносятся между устройствами | `bake-rootfs.py` вычищает `/var/lib/carthing-state` при каждом бейке |
| 2026-06-17 | Mode-aware resource policy: `resource_policy.py`, CPU governor diagnostics, optional `S11-zram`, runtime-state `resource_policy`, ALS/proximity diagnostics, and safe-unplug через центральный Play Now teardown | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260617-235414`, rootfs sha256 `362c4290d37cb7a5b1a93c2def85d9c0bd4d504487f7cfaa943bc327535ec17e`, runtime tree sha1 `e3e456c79ad0712a3c54549b71acd97dc4e7b6b1` |
| 2026-06-18 | Route-load/manual-background-policy: route-scoped Fosi standby, Play Now releases speaker ACL, periodic `LinkManager` polling disabled, `speaker_scan` manual/event-driven, proof script `tools/route-load-proof.sh`, iPhone stickiness preserved | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-013904`, rootfs sha256 `f5b6b1994c45174fef66d8947b0dd49679ebebe93bf70f5d7e545a512cbfb4ac`, runtime tree sha1 `856683dc1506cab30070c0229ca44aef1330ed48`; proof `docs/ROUTE-LOAD-PROOF-2026-06-18.md` |
| 2026-06-18 | Commutator snapshot standby: one-shot trusted-output scan on Коммутатор entry, hold all found online outputs, Play Now clears all external output footprints, Route-view mode/status line, external outputs dimmed in Play Now | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-015815`, rootfs sha256 `174ad69defe7a2edf4ed857ef61cf513e90b81766c2769109de2268fae2ed589`, runtime tree sha1 `1dd0d1d9ab0e2cdad4662c665eb2caeee3487b61`; proof `artifacts/route-load-20260618-015708/proof.json` |
