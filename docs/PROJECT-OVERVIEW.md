# Car Thing — открытая платформа

> **Статус 2026-06-17:** этот файл остаётся обзором/позиционированием проекта и
> содержит исторические фрагменты старой структуры. Для исполняемой инструкции
> с нуля используй [`GETTING-STARTED-FROM-ZERO.md`](GETTING-STARTED-FROM-ZERO.md),
> для текущего flash/bake цикла —
> [`BUILD-AND-FLASH.md`](BUILD-AND-FLASH.md), для фактического baseline —
> [`PRODUCT-BASELINE-2026-06-17-QN19.md`](PRODUCT-BASELINE-2026-06-17-QN19.md).
> Не считать актуальными команды и пути вида `carthing_full_real/`,
> `source/overlay`, `source/bake-rootfs.py`, `tools/recovery` и
> `tools/bring-up-network.sh` из старого текста ниже.

**Hook:** Это не «попытка взломать Car Thing». Это **полная открытая платформа**, построенная с нуля: вскрытый Apple MFi-чип (чего не сделал ни один публичный проект), свой Bluetooth-роутер на Bumble, собственный Linux на Buildroot, GUI в DRM без сторонних библиотек — и всё это без закрытых бинарников Spotify.

Самый глубокий реверс-инжиниринг из всех Car Thing проектов на GitHub: каждый чип на плате, каждая шина, каждый протокол.

Образ строится на `frederic/superbird-buildroot` (ОС) и заливается инструментом из линии `bishopdynamics/superbird-tool` (флешер).

> История разработки (с датами, старт 2026-03-30) — [`HISTORY.md`](HISTORY.md). Глубина реверс-инжиниринга, всё что вскрыто — [`RESEARCH.md`](RESEARCH.md). Результаты экспериментов — [`experiment/`](experiment/).

## Почему это лучшая реализация

Сравнение с основными GitHub-проектами:

| Проект | Путь | Ограничения | Это проект |
|--------|------|-------------|------------|
| [`frederic/superbird-buildroot`](https://github.com/frederic/superbird-buildroot) | Сырой Buildroot + ядро 4.9 | Только базовая система, нет runtime/Bluetooth/GUI | У нас — **полная продуктовая ОС** с Bluetooth-роутером, ANCS, A2DP, GUI, транскодером |
| [`bishopdynamics/superbird-tool`](https://github.com/bishopdynamics/superbird-tool) | Прототип flashing-инструмента | Не завершён, без скриптов сборки | У нас — **полный CI/CD**: `bake-rootfs.py`, `flash.py`, воспроизводимые build artifacts |
| [`err4o4/spotify-car-thing-reverse-engineering`](https://github.com/err4o4/spotify-car-thing-reverse-engineering) | Карта железа + прошивка stock | Только дампы и схемы, без runnable образа | У нас — **всё, что вскрыто**: MFi auth протокол, USB-C MAX20332, 4 микрофона, T9015, драйверы |
| [`usenocturne/nocturne-image`](https://github.com/usenocturne/nocturne-image) | Debian 12 поверх | Тяжёлый дистрибутив, BlueZ/BluetoothD, завязка на desktop-паттерны | У нас — **минималистичный Buildroot**: 512MB rootfs, свой BT-стек без BlueZ, modular compositor |
| `thinglabsoss/...` | Множество экспериментов | Нет единого релиза, баланс между стоком и кастомом | У нас — **единый baseline**: bootfs/rootfs/overlay чётко разделены, clean room |

**Ключевые достижения, которых нет у конкурентов:**

- ✅ **Clean-room доступ к Apple MFi-чипу** — вскрыт протокол ACP 3.0, живьём доказаны извлечение сертификата (PKCS#7) и подпись challenge (никто другой не сделал)
- ✅ **Bluetooth-роутер** — dual-mode (BLE + classic A2DP) на одном MAC, граф маршрутов, per-peer коммутатор (все конкуренты используют BlueZ, непрозрачно)
- ✅ **Звук на «немом» устройстве** — T9015 ЦАП + свой SBC-декодер (bit-exact с ffmpeg) + Helix AAC → A2DP iPhone играет в аналог (у конкурентов нет working audio output)
- ✅ **GUI PIL→DRM** — прямой вывод без LVGL/веб-киоска, modular compositor, поворот кадра, BT-петля (конкуренты используют тяжёлые UI-билиотеки)
- ✅ **Полный инвентарь железа** — каждый I2C-адрес, каждый драйвер, статус спящих функций (другие проекты только базовый дамп)

---

**Образ** (`image/`): кастомный Linux для Car Thing (Superbird).
- тема «Терминал» (единственная, без переключателя)
- персистентный раздел `p1` = **vfat**
- без retired-мусора, все файлы — владелец root
- runtime + GUI (modular Compositor), BT-стек, транскод/line-out

---

## Требования (Mac)

```sh
pip3 install pyusb 'pyamlboot @ git+https://github.com/superna9999/pyamlboot'
# только для пересборки образа (Part 2):
brew install e2tools e2fsprogs
```

## Размер образов

| Файл | Размер | Назначение |
|------|--------|------------|
| `image/rootfs.img` | 512 MB | Full rootfs (512M, 21% заполнен) |
| `image/bootfs.bin` | 172 MB | Boot partition (bootargs, Image, initrd, superbird.dtb) |
| `source/base-bundle/rootfs.img` | 184 MB | Baseline rootfs (исходник для пересборки) |
| `source/base-bundle/bootfs.bin` | 172 MB | Baseline bootfs |

**Общая полезная нагрузка:** ~868 MB для полной перепрошивки.  
**Балласт:** отсутствует — в репозитории только рабочие образы и исходники.

---

## Структура

```
carthing_full_real/
├── image/            готовый к прошивке образ (bootfs.bin, rootfs.img, env.txt, boot/, manual/)
├── tools/
│   ├── flash.py            прошивка одной командой
│   ├── check-device.sh     состояние устройства по VID:PID
│   ├── bring-up-network.sh поднять USB-сеть на Mac
│   ├── finish-env.py        дописать только env (если нужно)
│   ├── _flasher.py          низкоуровневый Amlogic-флешер (используется flash.py)
│   └── recovery/            доступ к устройству, если SSH недоступен
├── source/
│   ├── overlay/            слой проекта (исходники, что лежат в rootfs)
│   ├── base-bundle/        аппаратный baseline (ядро/bootfs) — вход для пересборки
│   └── bake-rootfs.py      сборка чистого rootfs из base-bundle + overlay
└── LICENSE                 GPL-2.0-or-later + атрибуция апстримам
```

---

# PART 1 — ПРОШИВКА (от USB до GUI)

### Шаг 1. Вход в Maskrom (USB Mode)
1. Выдерни USB-кабель.
2. Зажми и держи кнопки **1 и 4** (крайняя левая + крайняя правая верхние).
3. Воткни USB, не отпуская кнопки; держи ещё ~2 сек, отпусти.
4. Проверка:
   ```sh
   sh tools/check-device.sh        # -> MASKROM/BURN (1b8e:c003)
   ```

### Шаг 2. Прошивка
```sh
python3 tools/flash.py
```
Грузит временный U-Boot (BL2) → пишет `bootfs.bin` (sector 0) → `rootfs.img` (sector 352256) → `env` → `reset`. ~15–25 мин.

### Шаг 3. Холодная загрузка
1. Выдерни USB → подожди ~5 сек.
2. Воткни USB **без кнопок**.
3. Проверка (через ~3 мин):
   ```sh
   sh tools/check-device.sh        # -> BOOTED/NCM (0525:a4a1)
   ```

### Шаг 4. Сеть на Mac
```sh
sudo sh tools/bring-up-network.sh
```
Назначает `172.16.42.1` на интерфейс устройства, пинит маршрут `172.16.42.0/24`; устройство — на `172.16.42.77`.

> **⚠️ Важно для macOS — USB-сеть к устройству нестабильна, и это нормально, не пугайся:**
> - Интерфейс устройства **постоянно скачет и отваливается** (переэнумерируется: `en14` → `en15` → …). Если `ssh`/`ping` перестали отвечать — просто **повтори** `sudo sh tools/bring-up-network.sh`. Скрипт сам находит интерфейс и заново прописывает маршрут. Повторять можно сколько угодно раз.
> - **Не привязывайся к конкретному имени интерфейса.** Это не обязательно `en14` — имя может меняться при каждом переподключении.
> - **Если включён VPN** (Tailscale, WireGuard и т.п.) — он добавляет интерфейсы `utun*` и **перехватывает маршрут** к `172.16.42.0/24`, и трафик к устройству уходит не туда (на `utun`/другой `en`). Лечение: повтори bring-up (он переустанавливает маршрут), либо на время прошивки **выключи VPN**.
> - Состояние устройства определяй **по VID:PID, а не по интерфейсу/имени**: `sh tools/check-device.sh` (`0525:a4a1` = загружено, `1b8e:c003` = burn mode).

### Шаг 5. Тест GUI
```sh
ssh -o StrictHostKeyChecking=no root@172.16.42.77   # пароль: carthing
```
> Логин: `root`, пароль **`carthing`**. SSH-ключей в образе нет — при желании добавь свой публичный ключ в `/root/.ssh/authorized_keys`.
На устройстве:
```sh
grep "GUI active" /var/run/carthing/carthing-remote.log     # GUI active (modular Compositor)
grep '^THEME' /usr/lib/carthing/ui_theme.py                  # THEME = "terminal"
mount | grep mmcblk0p1                                        # type vfat
```
Посмотри на экран — интерфейс «Терминал».

---

# PART 2 — ПЕРЕСБОРКА образа (опционально)

Меняешь `source/overlay/` → пересобираешь чистый `image/`:
```sh
PATH="/opt/homebrew/opt/e2fsprogs/sbin:/opt/homebrew/bin:$PATH" \
python3 source/bake-rootfs.py --base-bundle source/base-bundle --output image
```
Берёт `base-bundle` (ядро/bootfs) + накладывает `source/overlay` → чистый `rootfs.img`: удаляет retired-файлы, владелец root, верифицирует.

При смене `overlay/usr/lib/carthing/*` обнови `EXPECTED_RUNTIME_TREE_SHA1` в `source/bake-rootfs.py` — скрипт при несовпадении печатает правильный sha.

---

# PART 3 — Доступ без SSH (recovery)

Если SSH недоступен, а устройство загружено (`0525:a4a1`): на устройстве крутится `reverse-agent`, который поллит Mac за командами.
```sh
# на Mac, в фоне:
python3 tools/recovery/reverse-control-server.py
# поставить команду в очередь:
sh tools/recovery/reverse-agent-enqueue.sh '<shell-команда>' device1
# результат:
cat /tmp/carthing-control-server/completed/device1/*.json
```

---

**Карты разделов eMMC:** `bootfs.bin` → sector 0; `rootfs.img` → sector 352256 (byte 180355072). `p1` (vfat) внутри bootfs держит boot-файлы (Image/initrd/superbird.dtb/bootargs.txt) и state.

**Лицензия:** GPL-2.0-or-later — образ содержит GPL-компоненты (ядро Linux, BusyBox, Buildroot-userspace). Апстримы (frederic/superbird-buildroot, bishopdynamics/superbird-tool) и условия — см. [`LICENSE`](LICENSE).
