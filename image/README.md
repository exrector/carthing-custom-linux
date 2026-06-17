# Flash image — Car Thing (Superbird)

Готовый к прошивке образ кастомного Linux (Buildroot) для Car Thing — открытая система, а не модифицированный сток.

- тема «Терминал», `p1` = vfat, владелец файлов root, без retired-мусора
- runtime + GUI (modular Compositor), BT-стек, GE2D userspace, native AAC/SBC codec libs
- release debug profile: `quiet` by default; SSH stays on, HTTP/telnet/reverse-agent stay off
- **логин: `root` / пароль `carthing`** (SSH-ключей нет — добавь свой в `/root/.ssh/authorized_keys` при желании)
- hardware baseline: GE2D kernel in `bootfs.bin`, clean Linux/CarThing bootargs, 512M rootfs, rescue NCM (`CONFIG_USB_G_NCM=y`) для SSH после каждой загрузки
- runtime tree sha1: `e3a530efa4bfd45be7335091831738ca342342af`

## Включение в репозиторий

Бинарные образы лежат локально в `image/`, но **не включены в git**:
они перечислены в `.gitignore`. Источник истины для проверки — `SHA256SUMS`
и локальные файлы на этой машине.

- `image/rootfs.img` (512 MB) — готовый к прошивке rootfs
- `image/bootfs.bin` (172 MB) — boot partition с ядром/DTB
- Если нужно исключить — см. `../.gitignore`

## Содержимое

| Файл | Назначение |
|---|---|
| `bootfs.bin` | пишется на sector 0 (MBR + vfat p1: Image, superbird.dtb, bootargs.txt) |
| `rootfs.img` | пишется на sector 352256 |
| `env.txt` | U-Boot env |
| `meta.json` | манифест шагов |
| `boot/` | bl2 + bootloader для входа в USB Burn Mode |
| `manual/` | self-contained superbird-флешер |

Прошивка — см. [`../README.md`](../README.md): `python3 tools/flash.py`.
