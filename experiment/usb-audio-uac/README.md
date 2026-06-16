# USB Audio (UAC) gadget на Car Thing (результат)

**Что это:** Car Thing поднят как **USB Audio Class gadget** — то есть как USB-звуковая карта / аудио-мост по USB (UAC через configfs); ещё один интерфейс устройства, открытый наружу. Плюс здесь зафиксирована эволюция всего **USB-gadget профиля** Car Thing (NCM-сеть, mass-storage/disk-mode, аудио) — как из одного USB-контракта переключать функции.

Готовый результат: рабочие скрипты UAC-gadget + сниппеты configfs + история USB-профиля + macOS-снэпшот того, как это видно с хоста.

## Что доказано / достигнуто

- **UAC-gadget**: Car Thing отдаёт себя хосту как USB-аудиоустройство (`carthing-uac2-bridge.sh`, `uac2-configfs-snippet.sh`, `DEPLOY-UAC1.md`).
- **USB-профиль управляем**: один gadget переключает функции (NCM / storage / audio) через configfs — эволюция `S04-usbgadget` от v1 к v4-FINAL зафиксирована с диффами.
- **macOS-сторона задокументирована**: как gadget виден в `ioreg`/`networksetup`/USB (снэпшот `macos-snapshot/`).

## Файлы

| Путь | Что |
|---|---|
| `uac2-bridge/carthing-uac2-bridge.sh` | поднятие UAC2-аудио-gadget |
| `s04-snippets/uac2-configfs-snippet.sh` | configfs-сниппет UAC2 |
| `s04-snippets/usb-strings-snippet.sh` | USB-строки gadget |
| `docs/DEPLOY-UAC1.md` | развёртывание UAC1 |
| `usb-gadget-evolution/` | `S04-usbgadget` v1→v4-FINAL + диффы, disk-mode, usb-profile |
| `macos-snapshot/` | как gadget виден с Mac (ioreg/usb/route/arp) |
| `CHANGE-LOG.md` | лог изменений USB-профиля/аудио |

## Примечание
Рядом — отдельный мини-реверс системного меню стоковой прошивки (`system_menu.py`), приложен в `misc/`.
