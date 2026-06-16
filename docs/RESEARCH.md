# Car Thing — глубина реверс-инжиниринга

Полная карта того, что вскрыто в устройстве — снизу доверху, от неизменяемого BootROM до userspace-интерфейсов. Это сводный результат месяцев раскопок: каждый чип на плате, каждая шина, каждый протокол. Глубже, чем доходил любой публичный проект по Car Thing — здесь устройство разобрано до уровня регистров и собрано заново как открытая платформа.

---

## Загрузочная цепочка (снизу вверх)

```
BL2 (Amlogic, неизменяем)        инициализирует DRAM, передаёт BL33
   └─ BL33 (U-Boot, стоковый)    LCD ST7701S DSI init, eMMC, USB PHY;
        │                        читает bootargs.txt → cmdline; грузит Image+initrd+superbird.dtb
        └─ Kernel 4.9.113 BSP     поднимает драйверы, отдаёт userspace /dev,/sys,/proc
             └─ Userspace         своя система поверх
```
Граница вмешательства проведена сознательно: **загрузчик не трогается** (стоковый Amlogic U-Boot `v1.0-74`), открывается только всё, что выше. SoC — **Amlogic G12A** (S905D2-класс, arm64).

**Почему ядро 4.9, а не современное.** Переход на mainline/community-ядро **6.6** (`alexcaoys/linux-superbird-6.6.y`, на базе RE err4o4) пробовали и отбросили: под 6.6 пришлось бы **с нуля портировать vendor-драйверы** G12A — LCD-панель, ЦАП T9015, MFi, сенсоры, — которые стоковый **4.9.113 BSP уже содержит рабочими**. Решение: переиспользовать 4.9 BSP как данность, а всё новое строить в userspace. Это сознательный инженерный выбор, а не «старое ядро по инерции».

---

## Карта железа (по подсистемам, с адресами)

### Дисплей
- LCD-контроллер `amlogic,lcd-g12a` (панель ST7701S, 480×800) → `/dev/lcd`, `/sys/class/lcd`
- DRM/KMS `/dev/dri/card0`, framebuffer `/dev/fb0`, VPU `/sys/class/vpu`
- Подсветка `/sys/class/backlight/aml-bl` (0–255, управляема из userspace)

### Ввод и сенсоры
| Компонент | Шина | Адрес | Интерфейс | Статус |
|---|---|---|---|---|
| Тачскрин tlsc6x | I2C-0 | `0x2e` | `/dev/input/event2` | активен |
| 4 кнопки | GPIO | — | `/dev/input/event0` | активен |
| Rotary encoder | GPIO | — | `/dev/input/event1` | активен |
| Акселерометр LIS2DH12 | I2C-2 | `0x18` | — | драйвер есть, спит |
| Свет/приближение TMD2772 | I2C-2 | `0x39` | `iio:device0` | драйвер есть, спит |
| USB-C мультиплексор MAX20332 | I2C-2 | `0x35` | — | без драйвера → управляем из userspace |

### Аудио
- ЦАП **T9015** (`ff632000.t9015`, ALSA card 0) — аналоговый выход
- 4× PDM-микрофона (`ff642000.audiobus:pdm`), capture `/dev/snd/pcmC0D0c`, loopback, `/dev/audiodsp0`

### Apple MFi authentication
- Чип на **I2C-3 `0x10`** (`apple_mfi_auth`) — **вскрыт полностью** (протокол ниже)

### Bluetooth
- Broadcom combo-чип, UART `/dev/ttyS1` @3 Мбит/с, `hci0`, `/dev/vhci`, `rfkill0`
- **Радио устройства — Bluetooth** (classic + BLE). WiFi не используется (ранние попытки оставлены как тупик)

### Криптография (hardware)
- Amlogic DMA crypto `ff63e000.aml_dma`: AES (`aml-aes`), 3DES (`aml-tdes`), SHA1/224/256 (`aml-sha`), HMAC (`aml-hmac`)

### USB
- `dwc2_a` (ff400000) — Device-режим (NCM gadget `usb0`); переключаем через configfs на Serial/Storage/Audio/Composite
- `dwc3` (ff500000) — Host (xHCI): plug&play USB-устройства

### Прочее
- Термозоны (5): soc / ddr / bluetooth / dram / pcb
- SAR-ADC `meson-g12a-saradc` (`iio:device1`); `efuse` (`usid`, `mac_bt`); `unifykeys` (secure storage); `hwrng`; `zram`; `uinput`; cpufreq DVFS (3 OPP-таблицы)

---

## Apple MFi auth-чип — вскрытый протокол (ACP 3.0)

Чип был заперт (закрытый userspace + не биндящийся драйвер). Получен clean-room доступ по сырой I2C, протокол восстановлен и доказан живьём.

- **Шина/адрес:** `/dev/i2c-3`, `0x10`. Семейство **ACP 3.0** (version `0x07`, auth-rev `0x01`, protocol `3.0`).
- **Регистры:** `0x10` control/status, `0x11` resp-len, `0x12` resp-data, `0x20/0x21` challenge, `0x05` error, `0x31` cert-stream, `0x4E` legacy-триггер.
- **Сертификат:** prepare → `0x31` → чтение 16-байтными чанками → **608 байт PKCS#7 signedData** (DER `30 82 02 5b`).
- **Подпись:** `0x21`+32-байтный challenge → `0x10 0x01` → поллинг `0x10` → `0x11`=`0x0040`, `0x12`=64 байта. **ECDSA over prehashed SHA-256.**

Полные данные, реальные запросы/ответы и инструмент — в [`experiment/mfi-chip/`](experiment/mfi-chip/).

---

## Bluetooth-стек — от чипа до кода (без BlueZ)

```
BCM combo-chip → /dev/ttyS1 (UART)
   → btattach-mini: грузит .hcd firmware, регистрирует hci0, выходит
   → kernel hci0 (raw HCI socket — НЕТ BlueZ, НЕТ bluetoothd)
   → Bumble (userspace): HCI→Host→L2CAP→SMP→GATT/ATT→A2DP/AVDTP/AVRCP
   → Device (единственный владелец контроллера)
   → AccessoryOrchestrator (фазовая машина PAIRING→BOTH_BONDED→READY; единый HCI-lock)
   → runtime: ANCS, AMS, A2DP-мост, HID, маршрутизация
```
Весь стек — в userspace на Bumble. Подробности — в [`experiment/bluetooth-router/`](experiment/bluetooth-router/).

---

## Спящие возможности (доступны без правок ядра и загрузчика)

Ключевой вывод раскопок: **ядро отдаёт значительно больше, чем использовала стоковая прошивка.** Доступно прямо сейчас:

| Возможность | Через что | Сложность |
|---|---|---|
| Автояркость / proximity | TMD2772 → backlight | низкая |
| Ориентация / wake-on-motion | LIS2DH12 | низкая–средняя |
| Локальное воспроизведение звука | T9015 + ALSA | низкая (сделано → audio-transcode) |
| Запись с микрофонов (wake word) | PDM + ALSA capture | низкая |
| Hardware crypto (AES/SHA/HMAC) | aml-crypto | средняя |
| USB-host периферия | dwc3 xHCI | низкая |
| Смена USB-gadget режима | dwc2 configfs | средняя (сделано → usb-audio-uac) |
| Управление USB-C портом | MAX20332 по I2C | средняя |
| iAP2 поверх MFi | apple_mfi_auth | высокая (сделано → mfi-chip) |

---

## Прошивка и доступ (методика)

- Вход: **Maskrom** (зажать 1+4 при подключении) → USB-устройство `1b8e:c003`.
- Затем **USB Burn Mode** (загрузка временного U-Boot/BL2) → запись на eMMC.
- Раздел `p1` (vfat) держит boot-файлы (`Image`/`initrd`/`superbird.dtb`/`bootargs.txt`) + state; rootfs пишется raw на сектор 352256.
- Низкоуровневый вход освоен через линию `superbird-tool` / `superbird-bulkcmd` / `amlogic-usbdl`.
- Жёсткое правило: **никогда `fastboot unlock`** — необратимый кирпич.

Воспроизводимая прошивка — корневой [`README.md`](README.md).

---

## Итог

От неизменяемого BL2 до каждого I2C-адреса, от регистров MFi-чипа до полного BT-стека в userspace — устройство вскрыто на всю глубину и задокументировано. Это и есть мера проекта: не «UI поверх стока», а полное понимание и контроль железа, которого нет ни у одного публичного Car Thing проекта.
