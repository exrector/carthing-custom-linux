# Car Thing — Research Log

Живой лог исследований. Дополнять снизу, не перезаписывать.

---

## 2026-05-22 — Сессия: реверс уровней 0-1-2, загрузка исходников

### Контекст

Цель сессии: понять что реально можно изменить в boot stack (уровни 0-1-2),
загрузить исходники, зафиксировать знания.

---

### Карта изменяемости boot stack

```
ROM Bootloader    ❌ кремний, недоступен — зашит в S905D2
BL2               ❌ подписан Amlogic ключом, ROM проверяет подпись — заменить невозможно
BL33 (U-Boot)     ✅ ПОЛНОСТЬЮ ЗАМЕНЯЕМ — BL2 просто прыгает на адрес, подпись не проверяет
Kernel            ✅ ПОЛНОСТЬЮ ЗАМЕНЯЕМ
Userspace         ✅ уже под контролем (уровни 3-4)

[кнопки 1+4]      ⚠️ аппаратный rescue в ROM — не трогать, это спасательный круг
```

**Ключевой вывод:** точка входа для "абсолютно нового" — BL33. BL2 передаёт управление
на фиксированный адрес без проверки содержимого (AVB2 отключён).

---

### Что делает оригинальный BL33 — разбор исходников spsgsb/uboot

Spotify-специфичные части в `board/amlogic/superbird_production/`:

**1. `include/spotify/hw_probe.h` — КРИТИЧНО сохранить логику**
- Читает ADC → определяет ревизию платы (REV_1..REV_12, по напряжению)
- Через I2C (адрес `0x2e`) опрашивает тачскрин контроллер `tlsc6x`
- Определяет производителя дисплея: BOE / Wily / Holitech
- Три разных дисплейных стека → разная инициализация LCD
- **Без этого дисплей не заработает или покажет мусор**

**2. `include/spotify/avb.h` — МУСОР, можно выбросить**
- Стандартный Android AVB A/B slot metadata
- Читает `misc` partition, выбирает активный слот
- AVB2 уже отключён, один слот — этот код не нужен

**3. `board/amlogic/configs/superbird_production.h` — что зашито:**
- `CONFIG_ENABLE_AVB_MODE "avb2"` + `AVB_USE_SPOTIFY_KEY 1` — Spotify ключ верификации
- `CONFIG_BOOTLOADER_CONTROL_BLOCK` — A/B механизм
- `CONFIG_PREBOOT` + `check_charger` — логика зарядки перед boot
- `CONFIG_ANDROID_BOOT_IMAGE` — Android boot image формат
- Всё это мусор для нашего use case

**4. `firmware/timing.c`** — DRAM timing инициализация. Критично — трогать осторожно.

**5. `lcd.c`** — инициализация LCD в U-Boot (splash). Можно упростить или убрать splash.

---

### Что даёт кастомный BL33 (гипотетически)

- Boot time: срезать с ~8-12 сек до ~2-3 сек (убрать AVB, A/B, charger check, splash delay)
- Убрать весь Spotify/Android код из bootloader
- Кастомный bootcmd — например, загрузка kernel с USB для разработки
- Прямая загрузка без A/B логики

---

### Что даёт кастомный Kernel (уровень 2)

Ключевые наблюдения из DTS (`meson-g12a-superbird.dts` в kernel-6.6):

- **SDIO закомментирован** — WiFi чип BCM4345C0 физически не распаян.
  SDIO контроллер в SoC есть. Потенциально: внешний WiFi модуль через SDIO (требует пайки).
- **Три производителя дисплея** (BOE/Wily/Holitech) — инициализация разная
- **GPIO 493** — reset BT чипа, сейчас костыль в userspace. В кастомном kernel можно
  сделать нативно в `hci_bcm` драйвере.
- **4× PDM микрофоны** — всегда включены, можно управлять питанием

Что можно получить от минимального kernel config:
- RAM под kernel: ~80-100MB → ~40-50MB
- Boot time (kernel→userspace): ~15-20 сек → ~5-8 сек
- Убрать Android-специфичный код (binder, ashmem, ion) — не нужен
- Кастомный `hci_bcm.c` — правильный power sequence нативно

---

### Загруженные исходники (sources/)

| Директория | Репозиторий | Назначение |
|------------|-------------|------------|
| `uboot/` | spsgsb/uboot | BL33 исходники (branch buildroot-openlinux-201904-g12a) |
| `kernel-stock/` | spsgsb/kernel-common | Kernel 4.9 stock |
| `kernel-6.6/` | alexcaoys/linux-superbird-6.6.y | Kernel 6.6 community port |
| `reverse-engineering/` | err4o4/spotify-car-thing-reverse-engineering | Патчи, DTB, исследования |
| `superbird-tool/` | bishopdynamics/superbird-tool | Инструменты flashing |
| `buildroot/` | frederic/superbird-buildroot | Buildroot overlay |

Все клонированы с `--depth=1`. Для полной истории: `git fetch --unshallow`.

---

### Правила проекта (зафиксировать)

- **BlueZ ЗАПРЕЩЁН** — только Bumble на raw HCI через `/dev/ttyS1` @ 3Mbps
- Устройство №1 — для рискованных экспериментов
- Устройство №2 — защищённое, не трогать

---

### Следующие шаги (не приоритизированы)

- [ ] Определить ревизию платы и дисплейный стек устройства №1 (через `dmesg` или ADC)
- [ ] Собрать кастомный U-Boot из исходников (убрать AVB/A/B/Spotify)
- [ ] Изучить kernel config в kernel-6.6 — что можно убрать под наш use case
- [ ] Исследовать `firmware/timing.c` — понять DRAM init sequence
- [ ] Проверить возможность нативного BT power sequence в `hci_bcm` драйвере

---

---

## 2026-05-22 — Данные с живого устройства №1

### Идентификация

| Параметр | Значение |
|----------|----------|
| Hostname | `Car Thing (SN: Q917)` |
| Serial (efuse usid) | `8559RP88Q917` |
| OS | Buildroot 2026.02.1-dirty |
| Kernel | 4.9.113 #1-NixOS SMP PREEMPT |
| U-Boot version | `v1.0-74-gfd61b37038` |
| Boot slot | `_a` (single slot, A/B не используется) |
| RAM total | 499556 kB (~488 MB) |
| RAM free | ~411 MB (устройство почти пустое) |

### Дисплей — КРИТИЧНО для кастомного BL33

```
panel_type = lcd_8
LCD chip:  ST7701S
Interface: MIPI DSI, 16bit
Resolution: 480×800
pixel_clk: 27.918 MHz
bit_rate:  670.032 MHz
```

**Тачскрин (tlsc6x):**
```
chip_code: 0x65c
vendor_id: 0x11  → это BOE (совпадает с BOE_VENDOR_ID=0x11, BOE_HW_ID=0x65c в hw_probe.h)
cfg_ver:   0x180e221a
irq GPIO:  415
rst GPIO:  414
```

**Вывод:** устройство №1 — дисплейный стек **BOE**. При сборке кастомного BL33 нужно
инициализировать именно BOE конфигурацию (или передавать `panel_type=lcd_8` в cmdline
и пусть kernel сам разбирается — что предпочтительнее).

### Bluetooth

| Параметр | Значение |
|----------|----------|
| Chip | BCM20703A2 |
| UART | `/dev/ttyS1` |
| BT MAC (efuse) | `30:e3:d6:04:c3:42` |
| GPIO reset | 493 (значение: 1 = активен) |
| btattach | `/usr/bin/carthing-btattach-mini /dev/ttyS1 115200` |
| Firmware files | `BCM.hcd`, `BCM20703A2.hcd`, `BCM4345C0.hcd` |

**Важно:** btattach стартует на 115200, потом переключается на 3Mbps.
`hciconfig` отсутствует — правильно, Bumble работает напрямую через HCI.

### Хранилище

| Partition | Размер | Точка монтирования |
|-----------|--------|--------------------|
| mmcblk0p1 | 31.9 MB | `/run/carthing-state` (77% занято) |
| mmcblk0p2 | 3641 MB | `/` (rootfs, 50.9MB занято из 477.8MB) |

Только 2 партиции видны в системе — A/B полностью убрано, один слот.

### Запущенные процессы (ключевые)

```
PID 609  carthing-btattach-mini /dev/ttyS1 115200
PID 612  [hci0]  ← kernel HCI thread
PID 623  python3 /usr/lib/carthing/media_remote.py
PID 214  dropbear (SSH :22)
PID 220  httpd :8080
PID 224  telnetd :2323
PID 229  python3 reverse-agent.py
```

### Init sequence (S-скрипты)

```
S01seedrng, S01syslogd, S02klogd, S02sysctl
S04-hostname → S05-usbnet → S06-ssh → S07-debug-http → S08-debug-telnet
S09-reverse-agent → S10-firmware-stage → S11-runtime-state → S11modules
S20-bt-init → S25-bt-metadata → S45-input-links → S50-carthing-remote
```

### Input devices

```
event0 → gpio-keys (кнопки)
event1 → rotary encoder
event2 → tlsc6x touchscreen
event3 → (появляется после boot)
```

Симлинки: `/run/carthing/input-buttons`, `/run/carthing/input-rotary`

### Kernel cmdline (полный, очищенный)

```
ramoops.pstore_en=1 ramoops.record_size=0x8000 ramoops.console_size=0x4000
rootfstype=ext4 console=ttyS0,115200n8 no_console_suspend
earlycon=aml-uart,0xff803000
root=/dev/mmcblk0p2 rootwait init=/bin/init
reboot_mode_android=normal
logo=osd0,loaded,0x1f800000 fb_width=480 fb_height=800
vout=panel,enable panel_type=lcd_8
frac_rate_policy=1 osd_reverse=0 video_reverse=0
irq_check_en=0
androidboot.selinux=enforcing androidboot.firstboot=0
jtag=disable
uboot_version=v1.0-74-gfd61b37038
androidboot.hardware=amlogic
androidboot.slot_suffix=_a
```

**Для кастомного BL33:** минимальный необходимый cmdline:
```
rootfstype=ext4 console=ttyS0,115200n8
root=/dev/mmcblk0p2 rootwait init=/bin/init
vout=panel,enable panel_type=lcd_8
fb_width=480 fb_height=800
```
Всё остальное — Android/Spotify мусор.

### Сеть

- USB NCM gadget: `usb0` на устройстве, `en14` на Mac
- Device IP: `172.16.42.77`
- Host IP: `172.16.42.1`
- SSH: `root@172.16.42.77:22`, пароль `carthing`

### Открытия

1. **Kernel modules: пусто** — `lsmod` показал только заголовок, нет загруженных модулей.
   Всё скомпилировано статически в kernel. Это хорошо для минимизации.

2. **Firmware в tmpfs** — `/lib/firmware/brcm` монтируется как tmpfs и заполняется
   скриптом `S10-firmware-stage` при каждом boot. Правильная архитектура.

3. **`/etc/superbird` и `/etc/machine-info` отсутствуют** — значит BT metadata
   (alias, hostname) либо не нужна для текущего use case, либо ещё не реализована.

4. **`carthing-state` partition (p1) на 77%** — стоит проверить что там хранится.


### Критическое открытие: carthing-state partition (mmcblk0p1)

Это **boot partition** — именно отсюда U-Boot загружает kernel!

```
/run/carthing-state/
├── Image          (14.8 MB) — kernel
├── initrd         (9.6 MB)  — initramfs
├── superbird.dtb  (104 KB)  — device tree
└── bootargs.txt   (552 B)   — kernel cmdline
```

**Это меняет всё для понимания boot flow:**
- U-Boot читает `bootargs.txt` → передаёт как cmdline
- U-Boot загружает `Image` + `initrd` + `superbird.dtb` из этой partition
- Чтобы поменять kernel/dtb — достаточно заменить файлы в этой partition
- **Не нужно перепрошивать eMMC через burn mode** для смены kernel

**ttyS1 после btattach:**
```
ispeed 4000000 / ospeed 3000000 baud  ← BCM переключился на 3Mbps (ospeed)
line = 15  ← HCI UART line discipline активна
```
Подтверждает: btattach отработал, HCI активен.

**media_remote.py лог:**
```
A2DP receiver setup failed: ConnectionError(hci/HCI_PAGE_TIMEOUT_ERROR [0x4])
HB: 0 conn + no adv — restart bonded reconnect advertising
Idle: no bond — silent, rejecting all (pairing not armed)
```
Устройство в idle, iPhone не подключён — нормальное состояние.


### bootargs.txt — точный cmdline от U-Boot

```
bootargs=ramoops.pstore_en=1 ramoops.record_size=0x8000 ramoops.console_size=0x4000
rootfstype=ext4 console=ttyS0,115200n8 no_console_suspend
earlycon=aml-uart,0xff803000
root=/dev/mmcblk0p2 rootwait init=/bin/init
reboot_mode_android=normal
logo=osd0,loaded,0x1f800000 fb_width=480 fb_height=800
vout=panel,enable panel_type=lcd_8
frac_rate_policy=1 osd_reverse=0 video_reverse=0
irq_check_en=0
androidboot.selinux=enforcing androidboot.firstboot=0
jtag=disable
uboot_version=v1.0-74-gfd61b37038
androidboot.hardware=amlogic
androidboot.slot_suffix=_a
```

Это файл который U-Boot читает и передаёт kernel. Можно редактировать напрямую
через SSH без перепрошивки bootloader.

### carthing-state/carthing/ — персистентное хранилище

```
iap2-link-keys.txt   (54 B)   — MFi/iAP2 link keys
keys.json            (394 B)  — BT pairing keys / bond store
trusted-devices.json (330 B)  — список доверенных устройств
```

Это единственные данные которые переживают перепрошивку rootfs.
При замене rootfs эти файлы остаются нетронутыми.


---

## 2026-05-22 — Быстрые тесты сомнительных интерфейсов

### SDIO / WiFi BCM4345C0 — НЕ РАСПАЯН ✗
- Нет второго MMC host в `/sys/class/mmc_host` (только `emmc`)
- SDIO контроллер не инициализирован
- GPIOX_6 (WiFi reset) = high — просто подтяжка, чипа нет
- **Вывод:** чип физически отсутствует на плате

### JTAG — ПРОГРАММНО ОТКЛЮЧЁН, пины есть ⚡
- Два JTAG порта описаны в DTB: `jtag_apao` и `jtag_apee`
- Пины: `TDI/TDO/CLK/TMS` для обоих портов
- Драйвер `amlogic,jtag` загружен (platform device активен)
- **НО:** в `bootargs.txt` стоит `jtag=disable` — Spotify отключила программно
- **Действие:** убрать `jtag=disable` из bootargs.txt → JTAG может заработать
- Если пины физически выведены на плату — полный CPU debugger (breakpoints, RAM dump)

### PCIe — ОТСУТСТВУЕТ ✗
- Нет PCI устройств, контроллер не инстанциирован в DTB
- Пины скорее всего не разведены на плату

### GPIO — неизвестные пины требуют исследования

```
gpio-414  ?              out hi   — неизвестный выход
gpio-460  ?              in  hi   — неизвестный вход
gpio-461  ?              in  hi   — неизвестный вход
gpio-462  ?              in  hi   — неизвестный вход
gpio-463  ?              in  hi   — неизвестный вход
gpio-465  ?              in  hi   — неизвестный вход
gpio-499  ?              in  hi   — неизвестный вход (aobus)
```

### gpio-498 avout_mute — АНАЛОГОВЫЙ АУДИОВЫХОД ⚡
- `avout_mute` = out hi → аудиовыход сейчас ЗАМЬЮЧЕН
- Это управление аналоговым выходом (3.5mm jack или внутренний динамик)
- `echo 0 > /sys/class/gpio/gpio498/value` → размьютить
- Связан с T9015 DAC — значит аналоговый выход физически есть

### gpio-482/483 — BT wakeup линии
```
gpio-482  host-wakeup    in  lo   ← BCM20703A2 → SoC (чип будит хост)
gpio-483  device-wakeup  out hi   ← SoC → BCM20703A2 (хост будит чип)
```
Эти линии позволяют реализовать BT low-power режим — чип спит,
просыпается по сигналу. Сейчас не используются из userspace.

### Следующие шаги по этим находкам
- [ ] Убрать `jtag=disable` из bootargs.txt и проверить JTAG
- [ ] Размьютить avout_mute и проверить аналоговый аудиовыход
- [ ] Идентифицировать gpio-460..465 через DTB анализ
- [ ] Реализовать BT wakeup через gpio-482/483


### Тест аналогового аудиовыхода (avout_mute / T9015 DAC)

**Результат:** аудиовыход физически есть, но не активирован на уровне DTB.

- `gpio-498 avout_mute` — занят драйвером `auge_sound`, не экспортируется
- ALSA card 0 имеет только **capture** (`pcmC0D0c` — PDM микрофоны)
- **Нет playback** (`pcmC0D0p` отсутствует) — T9015 DAC не поднят как ALSA playback
- `libasound`, `aplay`, `amixer` не установлены в образе

**Причина:** в DTB не настроен TDM DAI link для T9015 на playback.  
В `auge_sound` node нужно добавить `sound-dai` связку TDM → T9015.

**Что нужно для активации:**
- Добавить TDM playback DAI link в DTB (`auge_sound` node)
- Пересобрать и залить DTB
- После этого появится `/dev/snd/pcmC0D0p` → можно играть звук через T9015

**Это задача уровня 2 (DTB), не userspace.**


---

## 2026-05-22 — Аудио playback: итог сессии

### Что сделано

1. **Исправлена опечатка Spotify в DTB** — `dai-tdm-oe-lane-slot-mask-out` → `dai-tdm-lane-oe-slot-mask-out`
   Kernel никогда не читал это свойство из-за неправильного имени → `lane_oe_mask_out` всегда был 0.

2. **T9015 `tdmout_index` 1→0** — чип был настроен на TDMB, но TDMB не инстанциирован в DTB. Переключили на TDMA.

3. **Добавлен DAI link** в `auge_sound`: TDM-A → T9015, format=i2s, 48kHz stereo.

### Результат после прошивки патченного DTB

```
pcmC0D0p (playback) — появился ✅
T9015-audio-hifi <-> TDM-A mapping ok ✅
lane_oe_mask_out = 1 ✅
/dev/snd/pcmC0D0p открывается ✅
hw_params ioctl проходит ✅
writei — данные пишутся ✅
```

### Почему звука нет — корень проблемы

В `kernel-stock/sound/soc/amlogic/auge/tdm.c` строки 1257-1258 **закомментированы Spotify**:

```c
// aml_tdm_mute_playback(p_tdm->actrl, p_tdm->id,
//         mute, p_tdm->lane_cnt);
```

Функция `aml_dai_tdm_mute_stream()` вызывается при старте playback с `mute=1`, но ничего не делает.
Регистр `EE_AUDIO_TDMOUT_A_MUTE0` (адрес `0xff642000 + 0x52c`) остаётся `0xffffffff` навсегда.

Обойти из userspace невозможно — `/dev/mem` отсутствует (kernel собран без `CONFIG_DEVMEM`).

### Что нужно для финального шага

Раскомментировать 2 строки в `kernel-stock/sound/soc/amlogic/auge/tdm.c:1257-1258` и пересобрать kernel.
Патченный DTS сохранён: `sources/superbird-patched-audio-v1.dts`

### Следующий шаг

- [ ] Настроить toolchain для сборки kernel 4.9 (aarch64-linux-gnu-gcc)
- [ ] Раскомментировать tdm.c:1257-1258
- [ ] Собрать kernel, залить Image в carthing-state
- [ ] Проверить звук
