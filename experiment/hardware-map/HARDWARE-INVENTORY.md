# Car Thing — Полный инвентарь возможностей железа

**Дата:** 2026-05-22  
**Устройство:** №1, SN Q917  
**Принцип:** не "что убрать", а "что можно использовать"

---

## Что приходит из kernel в userspace — полная карта

### 🖥️ Дисплей

| Компонент | Устройство | Статус |
|-----------|-----------|--------|
| LCD контроллер | `amlogic,lcd-g12a` → `/dev/lcd`, `/sys/class/lcd` | ✅ активен |
| DRM/KMS | `/dev/dri/card0`, `/dev/dri/controlD64` | ✅ активен |
| Framebuffer | `/dev/fb0` (class `graphics`) | ✅ активен |
| Backlight | `/sys/class/backlight/aml-bl` | ✅ активен, 0-255 |
| VPU | `/sys/class/vpu` | ✅ активен |

**Backlight управляется из userspace:** `echo 128 > /sys/class/backlight/aml-bl/brightness`  
**Потенциал:** плавное затухание, автояркость (через датчик освещённости — см. ниже), sleep mode.

---

### 👆 Сенсоры ввода

| Компонент | Шина | Адрес | Устройство | Статус |
|-----------|------|-------|-----------|--------|
| Тачскрин tlsc6x | I2C-0 | `0x2e` | `/dev/input/event2` | ✅ активен |
| Кнопки (4 шт) | GPIO | — | `/dev/input/event0` | ✅ активен |
| Rotary encoder | GPIO | — | `/dev/input/event1` | ✅ активен |
| **Акселерометр LIS2DH12** | I2C-2 | `0x18` | — | ⚡ есть, не используется |
| **Датчик освещённости/proximity TMD2772** | I2C-2 | `0x39` | `/sys/bus/iio/devices/iio:device0` | ⚡ есть, не используется |

**LIS2DH12** — 3-осевой акселерометр ST Microelectronics. Даёт:
- Определение ориентации устройства
- Детектирование встряхивания / tap
- Детектирование движения (wake-on-motion)
- Потенциально: автоповорот UI, жест "взял в руку"

**TMD2772** — датчик освещённости + proximity (AMS/TAOS). Даёт:
- Автояркость дисплея по ambient light
- Proximity: определить что устройство поднесли к чему-то (например, к торпеде)
- Детектирование "в кармане" / "на столе"

---

### 🔊 Аудио

| Компонент | Устройство | Статус |
|-----------|-----------|--------|
| T9015 DAC (аудиовыход) | `ff632000.t9015`, ALSA card 0 | ✅ активен |
| PDM микрофоны (4 шт) | `ff642000.audiobus:pdm` | ✅ активен |
| PCM capture | `/dev/snd/pcmC0D0c` | ✅ активен |
| Audio loopback | `ff642000.audiobus:loopback` | ✅ активен |
| DSP | `/dev/audiodsp0` | ✅ активен |

**T9015** — TDM DAC, подключён к аудиовыходу (3.5mm jack или внутренний динамик).  
**4× PDM микрофона** — MEMS массив, capture уже работает через ALSA.  
**Потенциал:**
- Воспроизведение аудио через T9015 (не только BT relay — локально)
- Запись с микрофонов (wake word detection, voice commands)
- Audio loopback для тестирования
- DSP для обработки сигнала

---

### 🔐 MFi / Apple Authentication

| Компонент | Шина | Адрес | Статус |
|-----------|------|-------|--------|
| **Apple MFi auth chip** | I2C-3 | `0x10` | ✅ активен, драйвер `apple_mfi_auth` |

Это физический Apple MFi чип на плате. Через него можно:
- Аутентифицироваться как MFi-сертифицированное устройство перед iPhone
- Открывает путь к iAP2 (iPod Accessory Protocol 2) поверх USB или BT
- Потенциально: CarPlay accessory mode

---

### 🔒 Криптография (hardware-accelerated)

Amlogic DMA crypto engine (`ff63e000.aml_dma`):

| Алгоритм | Драйвер |
|----------|---------|
| AES-ECB/CBC/CTR | `aml-aes` |
| 3DES-ECB/CBC | `aml-tdes` |
| SHA1/SHA224/SHA256 | `aml-sha` |
| HMAC-SHA1/224/256 | `aml-hmac` |

**Потенциал:** шифрование данных на hardware без нагрузки на CPU. Полезно для:
- Шифрования bond store / ключей
- TLS без CPU overhead
- Подписи данных

---

### 🌡️ Термодатчики

| Зона | Тип | Текущая температура |
|------|-----|---------------------|
| `soc_thermal` | SoC | 32.3°C |
| `ddr_thermal` | DDR | 32.4°C |
| `bluetooth_thermal` | BT chip | 29.8°C |
| `dram_thermal` | DRAM | 29.7°C |
| `pcb_thermal` | PCB | 29.7°C |

**Потенциал:** мониторинг температуры, throttling при перегреве, отображение в UI.

---

### 📡 Bluetooth

| Компонент | Значение |
|-----------|---------|
| Chip | BCM20703A2 |
| UART | `/dev/ttyS1` @ 3Mbps (после attach) |
| HCI | `/dev/vhci` (virtual HCI для тестирования) |
| rfkill | `rfkill0` → `hci0` (software kill switch) |
| Thermal zone | `bluetooth_thermal` |

**`/dev/vhci`** — виртуальный HCI интерфейс. Позволяет эмулировать BT устройство без физического чипа. Полезно для разработки и тестирования Bumble без железа.

---

### ⚡ ADC (SARADC)

| Устройство | IIO | Назначение |
|-----------|-----|-----------|
| `meson-g12a-saradc` | `iio:device1` | Аналоговый вход |

SARADC используется U-Boot для определения ревизии платы (hw_probe). В userspace доступен через IIO. Можно читать напряжение на пинах — например, для определения состояния внешних аналоговых сигналов.

---

### 🔌 USB

| Контроллер | Режим | Статус |
|-----------|-------|--------|
| `dwc2_a` (ff400000) | Device (NCM gadget) | ✅ активен — `usb0` |
| `dwc3` (ff500000) | Host (xHCI) | ✅ активен |

**dwc3 — USB Host** — к нему можно подключать USB устройства:
- USB WiFi адаптер (альтернатива пайке SDIO)
- USB Ethernet
- USB Serial
- USB Audio
- USB HID устройства

**dwc2 — USB Device** — сейчас NCM (сеть). Можно переключить на:
- USB Serial (ACM) — для отладки
- USB Mass Storage — экспортировать раздел
- USB Audio — звук через USB
- Composite gadget — несколько функций одновременно

---

### 🧮 Прочее

| Компонент | Устройство | Потенциал |
|-----------|-----------|-----------|
| `uinput` | `/dev/uinput` | Создавать виртуальные input устройства из userspace |
| `zram` | `zram0` | Сжатый RAM-диск (swap в RAM) — увеличить эффективную память |
| `hwrng` | `/dev/hwrng` | Hardware random number generator |
| `efuse` | `/sys/class/efuse` | Уникальный ID устройства (usid, mac_bt) |
| `unifykeys` | `/dev/unifykeys` | Amlogic key storage (secure storage) |
| `binder` | `/dev/binder` | Android IPC — не нужен, но есть |
| CPU freq | `cpufreq-meson` | DVFS — управление частотой/напряжением CPU |
| OPP tables | `cpu_opp_table0/1/2` | 3 таблицы частот для разных режимов |

---

## Что НЕ используется сейчас но реально доступно

| Возможность | Через что | Сложность |
|-------------|-----------|-----------|
| Автояркость дисплея | TMD2772 ambient light → backlight | Низкая |
| Proximity detection | TMD2772 proximity | Низкая |
| Акселерометр / ориентация | LIS2DH12 | Низкая |
| Wake-on-motion | LIS2DH12 interrupt | Средняя |
| Локальное аудио воспроизведение | T9015 DAC + ALSA | Низкая |
| Запись с микрофонов | PDM + ALSA capture | Низкая |
| Hardware crypto | AES/SHA через /dev/crypto | Средняя |
| USB Host устройства | dwc3 xHCI | Низкая (plug & play) |
| USB gadget смена режима | dwc2 configfs | Средняя |
| Виртуальный input | uinput | Низкая |
| Температурный мониторинг | thermal sysfs | Низкая |
| CPU frequency control | cpufreq sysfs | Низкая |
| iAP2 через MFi chip | apple_mfi_auth I2C | Высокая |
| zram swap | zram0 | Низкая |

---

## Что приходит из каждого уровня

```
BL2 (Amlogic, неизменяем)
  └─ инициализирует DRAM, передаёт управление BL33

BL33 (U-Boot)
  └─ инициализирует: LCD (ST7701S DSI init sequence), eMMC, USB PHY
  └─ читает bootargs.txt → передаёт cmdline kernel
  └─ загружает: Image + initrd + superbird.dtb → передаёт управление kernel

Kernel
  └─ инициализирует все драйверы выше
  └─ предоставляет userspace интерфейсы:
     /dev/*, /sys/class/*, /sys/bus/*, /proc/*

Userspace (уровни 3-4)
  └─ использует всё что kernel предоставил
```

**Ключевой вывод:** kernel уже предоставляет значительно больше чем сейчас используется.
Акселерометр, датчик освещённости, proximity, аудио вход/выход, hardware crypto,
USB host — всё это доступно прямо сейчас без изменений в kernel или bootloader.
