# Тесты железа Car Thing: MAX20332 (источники питания) + USB-аудио

> **Назначение файла.** Единый сводный документ по двум аппаратным тестам, которые
> легко теряются, потому что сырьё разбросано по вложенному репо, архиву `.tar.gz`
> и curated-памяти агентов. Здесь — ЧТО протестировано, КАКИЕ результаты, и ГДЕ
> физически лежит каждый кусок. Если ищешь «те самые тесты MAX20332 с источниками» —
> ты на месте, дальше искать не нужно.
>
> Собрано: 2026-06-18. Источник истины — `carthing-release-architecture/archive/usb-charger-test-20260529/samples.log`
> (20 загрузок, снято 2026-05-29 на устройстве Q917) и `experiment/usb-audio-uac/`.
>
> **Перепроверено на живом QN19 2026-06-18:** дамп MAX20332 `0x35` совпал точь-в-точь
> (`00:2f 01:00 02:00 03:12 04:1f 05:00 06:00 07:0d 08:8e 09:8d 0a:00 0b:00 0c:00 0d:00 0e:09 0f:73`),
> reg03=`0x12` при udc=`configured`/carrier=`1` — устройство было на MacBook, что подтверждает строку
> CDP. Регистры `0x10+` → NAK. Логгер/S99 корректно отсутствуют (сняты при архивации), `i2c-tools` на месте.
> Ошибок не найдено — таблица актуальна.

---

## 0. Где что лежит (карта файлов — single source of truth)

| Что | Путь |
|---|---|
| **MAX20332 — сырьё 20 загрузок** | `carthing-release-architecture/archive/usb-charger-test-20260529/samples.log` |
| MAX20332 — README метода | `carthing-release-architecture/archive/usb-charger-test-20260529/README.md` |
| MAX20332 — логгер (boot-time, read-only) | `carthing-release-architecture/archive/usb-charger-test-20260529/max20332-logger.py` (и `carthing-release-architecture/tools/max20332-logger.py`) |
| MAX20332 — автостартер | `.../usb-charger-test-20260529/S99-max20332-log` (и `carthing-release-architecture/tools/S99-max20332-log`) |
| Общий зонд состояния устройства | `.../usb-charger-test-20260529/state_probe.py` |
| Весь kit одним архивом | `carthing-release-architecture/archive/usb-charger-test-20260529.tar.gz` |
| **USB-аудио (UAC) — весь эксперимент** | `experiment/usb-audio-uac/` |
| USB-аудио — живой лог тестов | `experiment/usb-audio-uac/CHANGE-LOG.md` |
| USB-аудио — снимок со стороны Mac | `experiment/usb-audio-uac/macos-snapshot/` |
| Одиночный снимок регистров MAX20332 (на компе) | `docs/HARDWARE-CAPABILITY-REVIEW-2026-06-18.md` |
| Декомпилированные DTS (live + audio-patch) | `carthing-device-backups/sources/{superbird-live-device1,superbird-patched-audio-v1}.dts` |

> ⚠️ `carthing-release-architecture/` — **вложенный отдельный git-репозиторий**.
> `git grep` / `git log` основного репо в него НЕ заходят. Искать там — только
> обычным рекурсивным `find`/`grep` по файловой системе.

---

## 1. MAX20332 — классификация источников питания (ВЫПОЛНЕНО)

### Что это
**Maxim/Analog MAX20332** @ I2C-2, адрес `0x35` — USB-C front-end: детектор зарядника
(BC1.2 SDP/CDP/DCP) + DPDT USB-свитч + OVP/ESD. Сидит на USB-C порту устройства.
Аккает на I2C **без драйвера** (в нашем DT узел без `compatible`, в стоковом —
`max20332@35`). Управляем из userspace через `/dev/i2c-2`.

### Метод (почему именно так)
Car Thing **без батареи** ⇒ каждое подключение к источнику = ПОЛНАЯ загрузка.
Поэтому read-only логгер автостартует на каждом boot, рано читает 16 регистров
MAX20332 (`0x00..0x0F`) + кросс-сигналы (`udc/state`, `usb0 carrier`), пишет с fsync
в persistent vfat (`/run/carthing-state/max20332/{samples.log,bootcount}`).
`bootcount` вместо RTC (батареи нет). **Кабель на детект не влияет** (проверено TB5 / USB-C / Apple).

Особенности устройства, заложенные в метод:
- на устройстве `subprocess`/shell = `ENOSYS` → всё через `/proc` + `sysfs`, без subprocess;
- `/tmp` read-only → писать только в `/run` или `/run/carthing-state`;
- `rcS` НЕ доходит до поздних S-скриптов → запуск повешен в `init-wrapper` (после `S50-carthing-remote`);
- busybox `watchdogd` уже армит `/dev/watchdog` (max 60с, NOWAYOUT off) — учитывать.

### Ключевой результат: дискриминатор источника = регистр `0x03`
Остальные регистры стабильны при любом источнике:
`00:2f  04:1f  07:0d  08:8e  09:8d  0e:09  0f:73` (00 = chip ID = `0x2f`).
Регистры `0x10+` → NAK.

| `reg03` | Класс по BC1.2 | Что подключали |
|---|---|---|
| `0x12` | **CDP** (компьютер) | MacBook Pro. `udc=configured`, `carrier=1`, данные + высокий ток |
| `0x11` | **SDP / стандартный порт** | NAS, роутер Keenetic, хабы (вкл. питаемые), тупой 5V USB-A зарядник. Различать по `udc`: `configured`=данные, `not attached`=тупое питание |
| `0x13` | **DCP** (выделенный зарядник) | Apple 35W, Anker iQ 65W, PD 35W, повербанк. ⚠️ PD/быстрые на этом слое НЕ различимы (PD идёт по CC-линии отдельно) |
| `0x15` | Apple 1A | классический USB-A divider |
| `0x1c` | Apple 12W / 2.4A | Apple USB-A divider |

### Полная таблица 20 загрузок (из `samples.log`, сэмпл s=1 на boot)

| BOOT | reg03 | udc | carrier | Источник |
|---:|:---:|:---|:---:|:---|
| 1 | `0x12` | configured | 1 | MacBook Pro (CDP) |
| 2 | `0x13` | not attached | 0 | Apple 35W (DCP) |
| 3 | `0x12` | configured | 1 | MacBook Pro (CDP) |
| 4 | `0x13` | not attached | 0 | Apple 35W (DCP) |
| 5 | `0x12` | configured | 1 | MacBook Pro (CDP) |
| 6 | `0x13` | not attached | 0 | Anker iQ 65W (DCP) |
| 7 | `0x13` | not attached | 0 | PD 35W (DCP) |
| 8 | `0x11` | not attached | 0 | 5V USB-A зарядник (SDP, тупое питание) |
| 9 | `0x13` | not attached | 0 | повербанк (DCP) |
| 10 | `0x1c` | not attached | 0 | Apple 12W / 2.4A |
| 11 | `0x11` | configured | 0 | NAS USB-A 3.0 (SDP, данные; carrier=0 = enumerate без NCM-bind) |
| 12 | `0x11` | configured | 0 | NAS USB-C 10G (SDP, данные) |
| 13 | `0x15` | not attached | 0 | Apple 1A |
| 14 | `0x11` | configured | 1 | роутер Keenetic (SDP, данные) |
| 15 | `0x11` | configured | 1 | хаб USB-A (SDP) |
| 16 | `0x11` | configured | 1 | хаб USB-C (SDP) |
| 17 | `0x11` | configured | 1 | питаемый хаб C-5G (SDP) |
| 18 | `0x11` | configured | 1 | питаемый хаб C-PD20W (SDP) |
| 19 | `0x11` | configured | 1 | питаемый хаб A-5G (SDP) |
| 20 | `0x12` | configured | 1 | MacBook Pro (CDP, повтор-контроль) |

**Вывод:** `reg03` + `udc` + `carrier` дают надёжную классификацию: компьютер vs
выделенный зарядник vs стандартный порт-с-данными vs тупое питание. Этого достаточно
для идеи «контекст-триггер при старте»: устройство читает `0x35` и понимает, во что
воткнуто (комп / розетка / зарядка / хаб-с-данными) → развилка «что поднимать».

### Ещё НЕ протестировано (заморожено — не было железа)
- автоадаптер в прикуриватель (12В авто);
- штатный USB магнитолы;
- charge-only кабель (без линий данных).

Барьер повторного запуска низкий: `i2c-tools` уже на устройстве, драйвер/ядро не нужны.

### Как переустановить логгер и догнать недостающие источники
На устройстве (`ssh carthing`):
```sh
mount -o remount,rw /
# положить max20332-logger.py -> /usr/sbin/  (chmod +x)
# положить S99-max20332-log -> /etc/init.d/   (chmod +x)
# хук в init-wrapper после S50-carthing-remote:
python3 - <<'PY'
p="/usr/libexec/carthing/init-wrapper"; s=open(p).read()
a="run_early_service /etc/init.d/S50-carthing-remote\n"
add="run_early_service /etc/init.d/S99-max20332-log\n"
if add not in s: open(p,"w").write(s.replace(a,a+add,1))
PY
sync; mount -o remount,ro /
echo 0 > /run/carthing-state/max20332/bootcount     # первое втыкание = BOOT 1
: > /run/carthing-state/max20332/samples.log
```
Забор: `ssh carthing 'cat /run/carthing-state/max20332/samples.log'`.

### Откат (как было при архивации)
Убрать строку `S99` из `init-wrapper`, удалить `/etc/init.d/S99-max20332-log` и
`/usr/sbin/max20332-logger.py` (rootfs rw → rm → ro). Self-heal `run-media-remote` —
НЕ трогать (отдельный постоянный фикс, не часть эксперимента).

### Не подтверждено
Register map MAX20332 из даташита не достали (зеркала Analog блокируют curl/WebFetch;
LLM-карты регистров галлюцинируют — ID/адреса не сходились, **не доверять**).
Классификация выше — чисто **эмпирическая** (диффом дампов по источникам), и она работает.
Даташит догнать позже для подтверждения смысла битов `reg03`.

---

## 2. USB как аудиоустройство (UAC gadget) — ВЫПОЛНЕНО

Полностью: `experiment/usb-audio-uac/`. Car Thing поднят как **USB Audio Class gadget**
(UAC через configfs) — то есть как USB-звуковая карта / аудио-мост по USB.

### Что доказано
- **UAC2-gadget**: устройство отдаёт себя хосту как USB-аудиоустройство.
  macOS видит `AppleUSBAudioControlNub` (=1 при включении, =0 при teardown).
- **USB-профиль управляем**: один gadget переключает функции (NCM / storage / audio)
  через configfs — эволюция `S04-usbgadget` от v1 к v4-FINAL зафиксирована с диффами.
- **macOS-сторона задокументирована**: `ioreg` / `networksetup` / USB-дескрипторы.

### Ключевые цифры из прогона (`CHANGE-LOG.md`, 2026-05-28, Q917)
- параметры потока: playback `p_srate=48000`, capture `c_srate=64000`, 2 канала, ssize=2;
- 3 цикла `ncm → ncm,audio → ncm` — «THE CRITICAL TEST» (teardown чистит `uac2`,
  binding на macOS = 0), затем idempotency-цикл — все зелёные, NCM пережил каждое
  переключение, SSH exit=0, 0 ребутов.

### Аппаратное ограничение (важно)
На контроллере `ff400000.dwc2_a` (Amlogic g12a, high-speed) **ACM нельзя держать
одновременно с NCM** — исчерпываются IN-endpoint'ы dwc2: `usb0 tx_packets` залипает
на 0, SSH/NCM умирают. Симптом — `tx_packets=0` при живом rx. Следить за бюджетом
endpoint'ов в композитных гаджетах.

---

## 3. Прочие находки по железу/драйверам (из curated-памяти агентов)

Подтянуто из `.claude/.../memory/carthing-hardware-map.md` и
`.codex/.../memory/carthing-claude-live-inventory-20260528.md` — чтобы не терялось:

- **T9015 DAC / аудио-playback** — доведён до `/dev/snd/pcmC0D0p`
  (`auge_sound: T9015-audio-hifi <-> TDM-A mapping ok`). Патч живёт в DT
  (`superbird-patched-audio-v1.dts` в `carthing-device-backups`).
- **LIS2DH12 (акселерометр)** — драйвер `st-accel-i2c` дожали, DT-узел корректный, но
  чип **молчит** на `0x18` (WHO_AM_I не читается). Стена — питание/распайка, не софт.
  На Q917 чип физически не запопулирован. Отрицательный результат зафиксирован.
- **TMD2772 (ALS + proximity)** @ `0x39` — живой (`iio:device0`), драйвер `tsl2x7x`.
- **Apple MFi auth** @ `0x10` (I2C-3) — отдельный эксперимент `experiment/mfi-chip/`.
- **Карта I2C (live i2cdetect):** bus0 `0x2e`=touch(UU); bus2 `0x35`=MAX20332,
  `0x39`=tmd2772(UU), `0x18`=accel(нет ACK); bus3 `0x10`=MFi(raw).
- **Полная карта подсистем ядра 4.9.113** (1297 опций `=y`, из `/proc/config.gz`) —
  в той же памяти.

---

## 4. Почему это было трудно найти (чтоб не повторялось)
1. `carthing-release-architecture/` — **вложенный git-репо**; история основного репо
   его не индексирует. Любой поиск «по истории» обязан включать обычный `find`/`grep`
   по ФС, а не только `git grep`/`git log`.
2. Часть сырья — в `.tar.gz` (текстовый grep не пробивает архив).
3. Аналитика метода жила в curated-памяти агентов (`~/.claude`, `~/.codex`), не в репо.

Свежие docs от 2026-06-18 (`docs/HARDWARE-CAPABILITY-*`) по этой причине ошибочно
числят тест MAX20332-по-источникам как «Tier B / ещё не сделано». **Он сделан** —
см. раздел 1. Этот файл — точка правды.
