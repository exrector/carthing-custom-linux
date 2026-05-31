# Car Thing Unified Runtime — полный цикл установки

Дата: 2026-05-31.

Цель: закрыть нижний слой как воспроизводимый hardware baseline и дальше
разрабатывать только userspace/runtime.

## Каноничный baseline

Основной install baseline:

```text
~/Documents/ПРОЕКТЫ/carthing-device-backups/artifacts/kernel-build-gcc6-nixos-20260524/flash-stock-plus-rescue-profile-20260525
```

Почему именно он:

- stock 4.9.113, GCC 6.5, без kernel 6.6;
- `/proc/config.gz` включён через IKCONFIG;
- USB configfs функции скомпилированы: NCM, ACM/serial, ECM, EEM, RNDIS,
  Mass Storage, UAC1, UAC2, MIDI, HID;
- `CONFIG_USB_G_NCM=y` оставлен как rescue path, поэтому macOS получает NCM/SSH
  после reboot;
- rootfs 512M;
- `profilectl` и профильная схема уже в rootfs;
- bundle был live-tested на Q917: NCM, ping, SSH, reboot.

Правило USB для релиза: после каждой нормальной загрузки default/rescue режимом
является NCM, чтобы не терять SSH и восстановительный доступ. Все остальные USB
функции не включаются на старте, а лежат как контролируемые профили, которые
должны переключаться с самого устройства через единый слой `profilectl` /
`usb-profile` и системное меню.

То есть USB Audio/Serial/HID/MIDI/Storage не выкинуты и не считаются
недоступными как возможности ядра. Они скомпилированы и вынесены в отдельные
переключаемые режимы. Релизная гарантия на старте только одна: устройство всегда
возвращается в NCM.

Семантика переключения: `usb-profile set <profile>` сначала применяет профиль
через `S04-usbgadget` и только после успешного применения сохраняет выбранное
значение. Если composite-профиль не поднялся и сработал fallback в NCM, такой
режим не должен становиться постоянным.

`flash-capability-profile-safe-20260525` и `flash-bake-ncm-20260530` не считать
финальным baseline, пока они не пройдут полный cold-boot + NCM + SSH + UI test
на №2.

## Userspace, который запекаем

Источник истины:

```text
(local repo root)
branch: release-integration
runtime tree sha1: b7963e251ab7e7a6f161c83a66d1303e0cbfe560
```

Запекаются 31 файл:

```text
overlay/usr/lib/carthing/*.py
```

Entry point:

```text
CARTHING_RUNTIME_ENTRY=/usr/lib/carthing/carthing_runtime.py
```

Boot chain не меняется:

```text
init-wrapper -> S50-carthing-remote -> run-media-remote -> carthing_runtime.py
```

## Сборка install bundle

```sh
cd (local repo root)
./scripts/bake-unified-runtime-rootfs.py
```

Скрипт создаёт новый каталог вида:

```text
flash-bake-unified-stable-YYYYMMDD-HHMMSS/
```

Внутри:

```text
bootfs.bin
rootfs.img
env.txt
meta.json
manual/
SHA256SUMS
README.md
```

Что делает bake:

- копирует проверенный `flash-stock-plus-rescue-profile-20260525`;
- не мутирует исходный bundle;
- накатывает unified runtime в `rootfs.img`;
- накатывает единые support tools из `overlay/usr/libexec/carthing`;
- выставляет `CARTHING_RUNTIME_ENTRY`;
- очищает отдельное A2DP имя/receiver, чтобы не возвращать `Car Thing Audio`;
- удаляет retired runtime-файлы, которые больше не должны оживать из старого rootfs;
- проверяет runtime tree hash внутри образа.

## Прошивка

Ввести устройство в USB Burn Mode:

```text
зажать 1+4 при подключении USB
```

На Mac должно быть видно:

```text
GX-CHIP
VID:PID 1b8e:c003
```

Проверка:

```sh
system_profiler SPUSBDataType | rg -i 'GX-CHIP|Amlogic|1b8e|c003'
```

Полная прошивка:

```sh
cd (local repo root)
./scripts/full-flash-bundle.py ./flash-bake-unified-stable-YYYYMMDD-HHMMSS
```

Скрипт пишет:

```text
bootfs.bin -> sector 0
rootfs.img -> sector 352256
```

После успешной записи скрипт отправляет `reset` через Burn Mode, чтобы устройство
само вышло в normal boot. Timeout на этой команде допустим: USB-контроллер
исчезает, потому что SoC перезагружается.

Fallback: если normal boot не появился, отключить питание/USB и включить без
кнопок.

## Первый normal boot

На Mac:

```sh
system_profiler SPUSBDataType | rg -i -C 4 'NCM Gadget|Car Thing'
networksetup -listallhardwareports | rg -n -C 2 'NCM Gadget|USB'
```

Если macOS видит NCM, но интерфейс не поднят:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

SSH:

```sh
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@172.16.42.77
```

## Acceptance test на устройстве

```sh
hostname
cat /sys/class/efuse/usid
uname -a
zcat /proc/config.gz | grep -E 'CONFIG_IKCONFIG|CONFIG_USB_CONFIGFS|CONFIG_USB_G_NCM|CONFIG_USB_CONFIGFS_F_UAC|CONFIG_USB_CONFIGFS_F_HID|CONFIG_USB_CONFIGFS_MASS_STORAGE|CONFIG_USB_CONFIGFS_F_MIDI'
cat /sys/class/udc/*/uevent
/usr/libexec/carthing/profilectl status
/usr/libexec/carthing/profilectl usb list
grep CARTHING_RUNTIME_ENTRY /etc/default/carthing
ps w | grep '[c]arthing_runtime.py'
tail -n 120 /run/carthing/carthing-remote.log
cat /run/carthing/runtime-bt.json
cat /proc/asound/cards
cat /proc/asound/pcm
df -h
```

Ожидается:

- hostname = `Car Thing (SN: XXXX)`;
- `/proc/config.gz` есть;
- `CONFIG_USB_G_NCM=y`;
- профиль USB по умолчанию = `ncm`;
- `/usr/libexec/carthing/profilectl usb list` показывает переключаемые USB
  профили;
- системное меню содержит USB-переключатели: NCM, NCM+Audio, NCM+Serial,
  NCM+HID, NCM+MIDI, NCM+Storage, Composite All;
- macOS видит `NCM Gadget`;
- SSH работает;
- `carthing_runtime.py` запущен;
- DRM GUI активен;
- iPhone Remote: AMS metadata, ANCS notifications, CTS time, encoder volume;
- Transfer может быть в коде, но не считается закрытым без отдельного live-test
  с Fosi/другим trusted speaker.

## Live acceptance: 2026-05-31

Прошитый bundle:

```text
flash-bake-unified-stable-20260531-verify
```

Устройство:

```text
Car Thing (SN: QN19)
/sys/class/efuse/usid = 8555R08SQN19
```

Flash result:

```text
BOOTFS: failures=0
ROOT: failures=0
```

В этой live-сессии normal boot был выполнен физическим переподключением без
кнопок. На будущее предпочтительный путь после успешной прошивки: отправить
software reset из Burn Mode, а физическое переподключение использовать только
как fallback.

Normal boot result:

```text
macOS USB product: NCM Gadget
VID:PID: 0x0525:0xa4a1
BSD interface: en14
device IP: 172.16.42.77
host IP: 172.16.42.1
ping 172.16.42.77: ok
SSH root@172.16.42.77: ok
```

Device-side acceptance:

```text
Linux Car Thing (SN: QN19) 4.9.113
CONFIG_IKCONFIG=y
CONFIG_IKCONFIG_PROC=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_NCM=y
CONFIG_USB_CONFIGFS_ECM=y
CONFIG_USB_CONFIGFS_RNDIS=y
CONFIG_USB_CONFIGFS_EEM=y
CONFIG_USB_CONFIGFS_MASS_STORAGE=y
CONFIG_USB_CONFIGFS_F_AUDIO_SRC=y
CONFIG_USB_CONFIGFS_F_UAC1=y
CONFIG_USB_CONFIGFS_F_UAC2=y
CONFIG_USB_CONFIGFS_F_MIDI=y
CONFIG_USB_CONFIGFS_F_HID=y
CONFIG_USB_G_NCM=y
UDC driver: g_ncm
USB profile: ncm
runtime entry: /usr/lib/carthing/carthing_runtime.py
runtime process: python3 /usr/lib/carthing/carthing_runtime.py
rootfs: 485.6M total, 432.0M available
```

Hardware/runtime evidence:

```text
ALSA card: AML-AUGESOUND
PCM 00-00: TDM-A-T9015 playback 1 / capture 1
PCM 00-01: PDM dummy capture 1
thermal zones: soc_thermal, ddr_thermal, bluetooth_thermal, dram_thermal, pcb_thermal
I2C 0-002e: tlsc6x_ts
I2C 2-0018: lis2dh12_accel
I2C 2-0039: tmd2772
I2C 3-0010: apple_mfi_auth
contract-selftest: ok
DRM GUI: active
runtime name: Car Thing (SN: QN19)
```

Вывод: этот bundle является первым физически прошитым и принятым hardware
baseline для перехода к userspace-only разработке.

## Что считается закрытым

После успешного acceptance test мы считаем закрытым нижний слой:

- bootfs/rootfs layout;
- stock-plus rescue/profile kernel;
- 512M rootfs;
- USB NCM recovery path;
- USB profile switch layer: `profilectl`, `usb-profile`, `S04-usbgadget`,
  system-menu entries;
- Bluetooth attach/HCI path;
- persistent state mount;
- GUI/runtime installation path.

Дальше меняется только userspace: файлы `overlay/usr/lib/carthing/*.py`,
настройки, GUI, сервисы и runtime-логика.

## Что не считается закрытым

- live-проверка каждого не-default USB профиля на macOS после переключения из
  меню устройства;
- USB Audio как реально распознанная и рабочая звуковая карта macOS;
- Mass Storage/HID/MIDI/Serial как физически подтвержденные USB режимы;
- CTKD classic link key;
- Transfer live relay;
- Mac source;
- assistant/proximity/default_mode.

Эти задачи относятся к userspace/runtime или к отдельному будущему hardware
baseline, но не блокируют закрытие текущей install architecture.
