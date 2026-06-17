# ⛔⛔⛔ ТОЧКА НЕВОЗВРАТА — `2136ace` = БАЗОВОЕ РАБОЧЕЕ СОСТОЯНИЕ (2026-06-14)

**Полный хэш:** `2136ace754932181b38c07bc47da29d0168d4370` — «Force terminal theme via env».
**Состояние устройства = `2136ace` + тема `a1021e2`, раздел p1 = vfat.** Доказанно рабочее. Git-тег: `base-pono-2136ace`.

**Для ЛЮБОГО агента в ЛЮБОЙ сессии — железно:**
1. Это НИЖНЯЯ граница. Любую фичу/реставрацию вести ТОЛЬКО ПОВЕРХ `2136ace`, не откатываясь ниже.
2. НИКОГДА не возвращать ошибки, угрожавшие устройству:
   - конвертация **самого p1** `vfat → ext4` (коммит `a7f691e`) = **кирпич** (U-Boot читает ядро с p1 только как FAT). **p1 ВСЕГДА FAT.**
   - реальный Linux `poweroff`/`halt` — уводит плату в Amlogic **burn mode**. Допустимо только «безопасное отключение» (suspend-to-RAM + remount-ro), без реального poweroff.
   - **Текущий продуктовый baseline (2026-06-17): p1 остаётся FAT и сейчас держит boot-файлы + малый runtime-state. p2 остаётся readonly rootfs.** Коммит `6358ad9` про state-on-p2 был откатан в `786e734` и НЕ является текущим поведением. Отдельный p3 НЕ входит в продуктовую архитектуру; считать его research/rejected, пока владелец явно не откроет эту тему снова. Crash-safety текущей линии = редкие записи, atomic `state.json`, backup/recovery и запрет бесполезных reboot после p1 writes.
3. Реставрация недостающих фич идёт в каноничный образ **`carthing_full_real`**, поверх baseline, без единого ext4-файла.
4. **ОДНА папка.** Вся разработка — в `carthing-release-integration` (+ `carthing_full_real` под чистый релиз). НЕ заводить новые папки в `~/Documents/ПРОЕКТЫ/` или `/tmp` под Car Thing: ни worktree-папок под ветки, ни `*-staging-*`/`*-backup`/`preservation-*`. Новая работа = новая **ВЕТКА**; изоляция от чужого дерева = коммит/stash; сохранение = коммит/bundle. Не folder.
5. **⛔ НЕ ребутать устройство командой `reboot` без крайней нужды.** 2026-06-15 ребут (ради теста recovery) увёл устройство в бутлуп. **КОРЕНЬ УСТАНОВЛЕН (2026-06-16, Claude):** агент записал в p1-FAT (`echo CORRUPTED > state.json`, `sync`) не размонтировав корректно → FAT остался в состоянии «improperly unmounted» → **U-Boot читает ядро `Image`/`initrd`/`dtb` с того же p1-FAT**, но его FAT-драйвер менее устойчив чем Linux → U-Boot сбоил/падал при чтении → hardware reset SoC → цикл. Kernel panic не было (pstore пустой — до ядра дело не доходило). Тестировать recovery — **рестартом рантайма**, не системы. Перед ребутом — `sync` + убедиться что p1 смонтирован чисто. **Recovery из бутлупа:** кнопки **1+4** + USB → Maskrom (`1b8e:c003`) → прошить ТОЛЬКО bootfs (rootfs трогать не нужно, он цел). Рабочий bootfs = `carthing-device-backups/device-full-backup-20260615-QN19/bootfs-region-0to352255.bin.gz` = `c3b76667` (уже скопирован в `carthing_full_real/image/bootfs.bin`). **ВНИМАНИЕ:** старый `carthing_full_real/image/bootfs.bin` (sha `7977c311`) — неправильный, не загружается. Актуальный = `c3b76667`. Бэкап: `carthing-device-backups/device-full-backup-20260615-QN19/`.
6. **Bootfs baseline после cleanup 2026-06-17:** валидный product bootfs = `957f91c3...` (`image/bootfs.bin` и `source/base-bundle/bootfs.bin`). Он основан на GE2D bootfs, FAT p1 очищен от macOS `._*`/`.fseventsd`, а Linux FAT16 state byte (`0x25`) очищен до `0x00`, чтобы ядро не видело раздел как dirty при каждом boot. Хеш `2ff2159a...` грузится, но содержит macOS metadata; `28f4b24a...` уже очищен от metadata, но всё ещё имеет выставленный Linux FAT dirty-state byte. Оба не должны снова попадать в bake/source bundle.

---

# ⛔ ИНВАРИАНТЫ — НЕ ЛОМАТЬ. Сверяться ПЕРЕД каждой правкой.

Этот файл = список доказанно работающих механизмов. Если что-то здесь работает —
**НЕ ТРОГАТЬ** без явного согласия владельца. Перед любой правกой BT/transfer/route —
прочитать этот файл и убедиться что правка не нарушает ни один пункт.

Дата фиксации: 2026-06-04.

---

## 1. Сопряжение iPhone (BLE + CTKD) — РАБОТАЕТ, ДОКАЗАНО

**Как работает:**
- iPhone парится по **BLE** (LE Secure Connections) → CTKD выводит classic link_key
  в ТУ ЖЕ запись keystore.
- Результат в `keys.json`: у iPhone (`10:A2:D3:83:82:50`) ОДНА запись с тремя ключами:
  `ltk` (BLE шифрование) + `irk` (BLE identity) + `link_key` (classic A2DP).
- После пары поднимается AMS (`AMS: ready`) → метаданные → Play Now.

**НЕЛЬЗЯ:**
- ❌ НЕ удалять/чистить `keys.json` по своей инициативе (приказ владельца).
- ❌❌❌ classic **discoverable=False ВСЕГДА**. Если classic discoverable — iOS видит
  Car Thing как classic-аудиоустройство (CoD) и парит **classic-FIRST**, игнорируя BLE →
  нет CTKD/AMS/Play Now. Обнаружение ТОЛЬКО по BLE-рекламе. (Ломал это дважды — НЕ возвращать
  `discoverable=pairing_armed`.)
- ❌ pairing_config_factory: `sc=True, bonding=True` + delegate с
  `SMP_LINK_KEY_DISTRIBUTION_FLAG` — это и даёт CTKD. НЕ убирать флаг.

**Признак что сломано:** у iPhone в keys.json только `link_key` без `ltk/irk` = битый
classic-only бонд. Лечение: забыть на iPhone + чистая пересоздача по BLE.

**Авто-forget при DHKEY_CHECK_FAILED (`_on_pairing_failure`):** при сбое BLE-пары код
авто-чистит битый бонд + resolving → iPhone ретраит → чистая пара. ❌ НЕ блокировать
авто-forget по `transfer_active`/`active_session==router` — с «трубой» transfer_active=True
ПОСТОЯННО, и это намертво вырубает авто-forget → iPhone вечно classic-only. Блокировать
ТОЛЬКО при реальном потоке (`source_stream_active`).

**Признак классики-онли в логе:** `connected classic=False` → `requesting pairing` →
`SMP_DHKEY_CHECK_FAILED_ERROR` → `keeping bonds` → потом `connected classic=True`.

---

## 2. Fosi (выходной динамик) — РАБОТАЕТ, ДОКАЗАНО

**Как работает:**
- Адрес: `C4:A9:B8:70:2F:E5`, имя «Fosi Audio ZD3», role=speaker.
- keys.json: classic `link_key` (только classic, БЕЗ ltk/irk — это нормально для колонки).
- state.json endpoints: `audio-output` → `classic_a2dp_source`, `remote-control` → `classic_avrcp`.
- Car Thing подключается к Fosi как A2DP **source** (мы шлём звук Fosi).
- `start_standby_loop()` держит Fosi подключённым/реконнектит с загрузки (звонит ТОЛЬКО
  спаренным колонкам с link_key).
- `A2DP stream opened+held` — канал к Fosi держится открытым.

**НЕЛЬЗЯ:**
- ❌ НЕ перенастраивать Fosi если работает. Бонд + endpoints выше = эталон.
- ❌ НЕ закрывать standby-канал к Fosi без причины (иначе переоткрытие при активном
  входящем A2DP от iPhone = `TimeoutError`, одно радио на чипе).

---

## 3. Транслирование звука iPhone → Car Thing → Fosi (ТРУБА) — РАБОТАЛО

**Как работает (доказано в логе 2026-06-04 11:01: `sent_to_speaker=True`):**
- iPhone выбирает Car Thing аудиовыходом → шлёт A2DP на Car Thing.
- `forward_packet` (a2dp_bridge): если `receiver_rtp_channel` (канал к Fosi) открыт →
  RTP-пакеты льются на Fosi автоматически.
- Условие работы: Fosi-канал ДОЛЖЕН быть открыт ДО того как iPhone начнёт стримить
  (иначе page к Fosi не пролезает через насыщенное входящим потоком радио).

**НЕЛЬЗЯ:**
- ❌ НЕ делать teardown/stop_receiver_stream когда труба работает.
- ❌ Кнопка активации НЕ должна сносить рабочий маршрут.

---

## 4. BLE-реклама — ДВА РЕЖИМА

- **Сканер открыт** (`pairing_armed=True`): general advertising С ИМЕНЕМ `Car Thing (SN: QN19)`
  → iPhone видит и может спариться.
- **Сканер закрыт** (`pairing_armed=False`): bonded-only БЕЗ имени → только знакомые
  реконнектятся, для чужих невидимо.

**НЕЛЬЗЯ:**
- ❌ НЕ глушить рекламу когда есть только classic-коннект (Fosi). Считать ТОЛЬКО
  BLE-соединения: `transport != BT_BR_EDR_TRANSPORT`.
- ❌ classic-инквайри (сканер колонок) глушит BLE-рекламу на одном чипе — после инквайри
  ОБЯЗАТЕЛЬНО возрождать рекламу (`apply_visibility`).

---

## 5. Имя устройства — ОДНО на все транспорты

- `identity_service.visible_name()` из efuse usid → `Car Thing (SN: QN19)`.
- Одно имя: BLE adv scan-response + GATT Device Name + classic Local Name + hostname.
- ❌ НЕ хардкодить имена. НЕ давать classic отдельное имя (иначе iPhone видит два устройства).

---

## 6. Идентичность устройств в trusted

- ❌ НЕ хардкодить первый BLE-бонд как «iPhone» — имя/ключ из реального адреса.
  (Иначе MacBook показывается как iPhone.)
- state.json = единый источник; iPhone enrollment дополняется из keystore (адрес+endpoints).

---

## 7. Появление Car Thing в аудиовыходах iPhone (Control Center) — рецепт Codex 2026-06-04

Для того чтобы iOS показал Car Thing как A2DP аудиовыход, НЕДОСТАТОЧНО просто A2DP Sink SDP.
Требуется (подтверждено: classic-коннект от iPhone был, но в выходах не появлялся без этого):
- **AVRCP Target SDP** (`0x110C` + AVCTP PSM `0x0017` + AVRCP profile `0x0106`) — iOS почти
  всегда требует AVRCP, чтобы продвинуть устройство в audio routing. Собрано вручную
  (`_make_avrcp_target_sdp_records`), т.к. в vendored Bumble нет helper'а.
- **CoD = `0x240414`** (loudspeaker), НЕ `0x240404` (wearable headset).
- **НЕ регистрировать AudioSource SDP** — только AudioSink. iPhone путается в ролях если видит оба.
- classic **discoverable при сопряжении** (pairing_armed) — iOS читает CoD+SDP только при паре.
- iOS **КЭШИРУЕТ** SDP → после любых правок SDP: forget на iPhone + чистая переспара.

❌ НЕ возвращать AudioSource SDP. НЕ менять CoD на 0x240404.

## ПРАВИЛО РАБОТЫ
Перед правкой любого из: `accessory_orchestrator.py`, `a2dp_bridge.py`,
`transfer_service.py`, `carthing_runtime.py` (route/transfer часть) —
**прочитать этот файл** и проверить что правка не ломает пункты 1-6.
Если правка касается рабочего механизма — спросить владельца.

---

## ADDENDUM 2026-06-04 — iPhone Control Center ещё НЕ доказан

Пункт 7 выше — рабочая гипотеза после правок SDP/CoD, но тест пользователя после
этой правки показал: **на iPhone в Control Center аудиовыход Car Thing не появился**.
Значит пункт 7 нельзя считать доказанным инвариантом до живого успешного теста.

Текущая проверяемая линия:
- CoD должен быть не только в `device.class_of_device`, а реально записан в контроллер
  через `HCI_Write_Class_Of_Device_Command` и прочитан обратно как `0x240414`.
- Classic EIR не должен противоречить SDP: для iPhone-facing образа устройства
  рекламировать `AudioSink (0x110B) + AVRCP Target (0x110C)`, а не `AudioSource`.
- После таких изменений всё равно нужен свежий iOS-cache: забыть Car Thing на iPhone
  и заново спарить, иначе iOS может держать старые SDP/CoD данные.

---

## ADDENDUM 2026-06-04 — MFi low-level ДОКАЗАН, Control Center по-прежнему не доказан

Живой тест после чистой BLE-first пары:
- iPhone подключился одним BLE-действием.
- AMS/ANCS/CTS поднялись.
- В keystore появились `irk` + classic `link_key` + BLE `ltk`.
- В trusted registry появился один `iPhone`, без дубля `Bluetooth Source`.
- Но `A2DP_SOURCE_OPEN` не было, и пользователь подтвердил: **Car Thing как аудиовыход
  в Control Center не появился**.

Вывод: plain BLE-first CTKD + `AudioSink` SDP + `AVRCP Target` SDP + CoD `0x240414`
не доказали iPhone audio-routing.

Classic-discoverable вариант тоже НЕ финальный: он давал classic-first подключение,
но затем iPhone показывал/требовал второй BLE-pairing row. Это нарушает цель “одна
пользовательская пара / один аксессуар”.

MFi/MFi-auth состояние 2026-06-04:
- Железный узел есть: `/sys/bus/i2c/devices/3-0010`, name `apple_mfi_auth`.
- В текущей rootfs изначально не было `/dev/apple_mfi` и `apple_mfi_ioctl`.
- Старые модули найдены:
  `~/Documents/ПРОЕКТЫ/carthing-device-backups/artifacts/kernel-build-gcc6-nixos-20260524/nixos-superbird/modules/sys/kernel/mfi/resources/apple-mfi-auth.ko`
  и `apple-mfi-auth-i2c.ko`.
- После live `insmod` + `mknod` проверка прошла:
  `MFI_VERSION=0x07`, `MFI_CERT_LEN=608`, `GET_RESPONSE` отдаёт PKCS#7 blob,
  `SET_CHALLENGE` + `GET_SIGNATURE` возвращает 64-byte signature.

Релизная правка:
- `S12-mfi-auth` грузит оба MFi-модуля до Bluetooth/runtime и создаёт `/dev/apple_mfi`.
- `hardware_inventory.py` различает `mfi_i2c_node`, `mfi_auth_driver`,
  `mfi_auth_device`, `mfi_auth_version`, `mfi_auth_cert_len`.

Следующая правильная линия: не возвращать хаотичное dual-pairing; строить iAP2/MFi
поверх доказанного `/dev/apple_mfi` и текущего единого runtime.

---

## ADDENDUM 2026-06-04 — BLE advertising НЕ должен говорить `BR/EDR Not Supported`

Гипотеза пользователя подтвердилась на уровне кода: Linux-side accessory должен
дать iPhone явный сигнал, что Classic BR/EDR доступен в этом же dual-mode
accessory.

Найденная ошибка:
- `accessory_orchestrator.py` и legacy `media_remote.py` использовали BLE flags
  `0x06`;
- `0x06` = `LE General Discoverable` + `BR/EDR Not Supported`;
- это делает первую iPhone-пару похожей на BLE-only accessory, даже если ниже уже
  есть CTKD, Classic SDP, A2DP Sink, AVRCP Target и MFi/iAP2.

Исправленный инвариант:
- для Car Thing dual-mode advertising использовать flags `0x1A`;
- `0x1A` = `LE General Discoverable` + `Simultaneous LE and BR/EDR Controller`
  + `Simultaneous LE and BR/EDR Host`;
- после этой правки обязательно перезапускать Bumble/runtime и делать чистую
  первую пару на iPhone (`Forget This Device`), потому что iOS кэширует первый
  accessory image.

Это не включает Classic discoverable как отдельное устройство. Classic остаётся
connectable/SDP-ready внутри единой dual-mode персоны, а пользовательская пара
должна оставаться BLE-first + CTKD.

---

## ADDENDUM 2026-06-04 — CTKD link-key должен быть CT2-capable

Живой post-pair Classic probe после успешной BLE/CTKD пары показал:
- BR/EDR ACL к iPhone открывается;
- локальный link-key provider находит CTKD-derived key;
- authentication падает `HCI_AUTHENTICATION_FAILURE [0x5]`.

Это доказывает, что проблема уже не в отсутствии Classic-маяка и не в отсутствии
link-key как файла. Проблема в совместимости самого BR/EDR link-key.

Найдено в vendored Bumble:
- `PairingConfig` не имел параметра CT2;
- `smp.Session.ct2` всегда был `False`;
- CTKD LE→BR/EDR link-key считался старой веткой `h6(ltk, "tmp1") -> h6(..., "lebr")`.

Исправленный тестовый инвариант:
- unified runtime включает `PairingConfig(..., ct2=True)`;
- Pairing Request/Response выставляет CT2 bit;
- если iPhone тоже выставляет CT2, link-key считается через CT2/h7 path;
- после этой правки снова нужна чистая первая пара (`Forget This Device` на iPhone
  + очистка local keystore), потому что старый link-key уже доказан невалидным
  для Classic authentication.

---

## ADDENDUM 2026-06-04 — iAP2 и post-pair Classic probe не включать в базовый first-pair

Живой тест с включённым `CARTHING_POST_PAIR_CLASSIC_PROBE=1` показал:
- после BLE/AMS пары Car Thing сам открывает BR/EDR ACL к iPhone;
- iOS начинает показывать отдельный Classic-facing слой;
- authentication падает `HCI_AUTHENTICATION_FAILURE [0x5]`;
- пользователь видит две подключённые строки и ещё одну готовую к подключению поверхность.

Вывод:
- post-pair Classic probe полезен как диагностика, но не должен быть default;
- iAP2/MFi RFCOMM/SDP surface тоже не должен включаться в чистом A2DP/CTKD first-pair
  тесте, потому что iOS может показывать generic `Accessory`/`Аксессуар` row;
- базовый аудио-тест должен быть только BLE HID/AMS/ANCS + Classic A2DP Sink/AVRCP
  Target + CoD loudspeaker + dual-mode BLE flags.

Текущее правило:
- `CARTHING_POST_PAIR_CLASSIC_PROBE=0` по умолчанию;
- `CARTHING_IAP2_ENABLE=0` по умолчанию;
- iAP2 включать отдельным тестом только после чистого аудио-first-pair baseline.

---

## ADDENDUM 2026-06-04 — Bumble runtime находится в карантине

После live-тестов iPhone dual-mode и появления лишних Bluetooth-поверхностей
Bumble больше не считается production-владельцем Bluetooth-чипа.

Инвариант релизной ветки:
- старый Bumble userspace остаётся на диске только как архив/лабораторный стенд;
- автозапуск Bumble-runtime запрещён;
- `/etc/default/carthing` держит `CARTHING_BUMBLE_QUARANTINE=1` и
  `CARTHING_ALLOW_BUMBLE_RUN=0`;
- init-скрипт переименован в `:S50-carthing-remote.disabled`, чтобы `rcS` не
  запускал его как `S??*`;
- `init-wrapper`, `run-media-remote`, `tools/run_local.sh`,
  `tools/run_local_main.py`, `tools/hci_proxy.py` и Fosi standalone-тесты должны
  отказываться от запуска без явного lab override.

Единственный допустимый временный запуск Bumble-тестов:

```sh
CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 <command>
```

Возвращать имя `S50-carthing-remote` в release image нельзя: это снова позволит
legacy runtime захватить HCI на загрузке.

---

## ADDENDUM 2026-06-05 — iPhone A2DP требует поддержки L2CAP Flush Timeout

Финальный аппаратный тест нашёл причину пустого Control Center после уже
успешной единой dual-mode пары:

- iPhone при настройке A2DP media channel передаёт L2CAP option
  `FLUSH_TIMEOUT=0x00C8`;
- vendored Bumble отвергал известную опцию ответом
  `FAILURE_UNKNOWN_OPTIONS`;
- стороны бесконечно повторяли L2CAP Configure, media channel не переходил в
  OPEN, поэтому iPhone не отправлял AVDTP `START`.

Обязательный инвариант vendored Bumble:

- существует и правильно сериализуется
  `HCI_Write_Automatic_Flush_Timeout_Command`;
- Classic L2CAP принимает `FLUSH_TIMEOUT`, сохраняет его как политику
  удалённого отправителя и отвечает Configure SUCCESS;
- значение из входящего L2CAP Configure нельзя применять к локальному
  контроллеру: направление и единицы L2CAP/HCI различаются;
- `scripts/check-bumble-vendor.py` проверяет HCI-команду, чтобы этот фикс нельзя
  было случайно потерять при обновлении vendor-кода.

Доказанный результат полного dual-mode runtime:

- используется одна уже созданная пара iPhone и Car Thing;
- активация Classic/A2DP на Linux-стороне автоматически подключает
  `Car Thing (SN: QN19)` и публикует его как аудиовыход в Control Center;
- iPhone выбирает AAC, открывает RTP, отправляет AVDTP `START`, передаёт
  реальный RTP-поток и AVRCP Absolute Volume.

Аппаратное доказательство:
`artifacts/dual-mode-20260605/dual-mode-flush-fix-success.log`.

Пока это проверено временным lab runtime из `/run/carthing-dual-mode-lab`.
Переживание перезагрузки требует отдельного bake release overlay в rootfs и
стандартной прошивки.

---

## ADDENDUM 2026-06-10 — ТРУБА iPhone → Car Thing → Fosi ДОКАЗАНА на свежем bond

Полный маршрут проверен живьём (музыка реально звучала из Fosi):

- чистая BLE-first пара iPhone → CTKD выдал новый полный bond (ltk+irk+link_key);
- classic-активация подключила iPhone, Control Center показал Car Thing,
  iOS стримил AAC (`A2DP_SOURCE_START codec=AAC`);
- Fosi спарен headless по адресу, AVDTP endpoints опрошены:
  **Fosi умеет AAC** (44.1/48 kHz stereo, VBR, до 320 kbps) и SBC;
- sink выбран AAC seid=3, канал открыт и держится ДО старта потока iPhone
  (инвариант п.3 соблюдён);
- `A2DP_BRIDGE_RTP forwarded=1750 dropped=0 sent_to_speaker=True` — сквозной
  AAC без транскодирования.

Новые проверенные механизмы (НЕ ломать):

- **Ретраи classic-дозвона**: `_resume_bonded_classic_audio` делает 3 попытки
  с паузами 3/8/15 c. Одна попытка через 1 c после старта почти всегда даёт
  `PAGE_TIMEOUT` — page гонится с BLE-реконнектом за одно радио. НЕ возвращать
  одноразовый дозвон.
- **`CARTHING_PAIR_SPEAKER=<addr>`**: однократный headless-enroll колонки по
  известному адресу (колонка в режиме пары) — без инквайри, без GUI.
  Полный цикл: forget старого ключа → SSP пара → enroll trusted → держать ACL.
- Деплой lab runtime: tar `overlay/usr/lib/carthing` → `/run/carthing-dual-mode-lab`,
  env: `CAR_THING_TRANSPORT=hci-socket:0`,
  `CAR_THING_KEYSTORE=/run/carthing-state/carthing/keys.json`,
  `CAR_THING_LIB=.../vendor`, `CARTHING_GUI_ENABLE=0`,
  `CARTHING_CLASSIC_AUDIO_RECONNECT=1` + lab override (карантин).
- busybox: процессы убивать ТОЛЬКО по PID из `ps` (pgrep -f не работает);
  runtime сам выходит после 8 неудачных попыток открыть занятый HCI.

Evidence: `artifacts/dual-mode-tests-20260610/` (run5 = труба, run4 = baseline,
SHA256SUMS). Бонды обоих устройств — в персистентном keystore
`/run/carthing-state/carthing/keys.json` (переживают ребут устройства).

Runtime по-прежнему lab-only (`/run/carthing-dual-mode-lab`) — НЕ переживает
ребут до bake (блок D ранбука docs/dual-mode-test-plan-2026-06-10.md).

---

## ADDENDUM 2026-06-10 (день) — AVRCP-КОММУТАТОР: backchannel Fosi ДОКАЗАН

Транспортные кнопки пульта Fosi управляют iPhone через Car Thing:
`AVRCP target key → backchannel: speaker_remote → source intent (AMS)`.
play/pause/next/prev работают live (run13). Громкость/mute ZD3 по BT НЕ шлёт —
обрабатывает локально в усилителе (это железо, не наш код).

Доказанные механизмы (НЕ ломать):

- **AVRCP-сессия НА КАЖДОГО ПИРА** (`avrcp_sessions{}` в a2dp_bridge). Возврат
  одного глобального `avrcp.Protocol` ЗАПРЕЩЁН: он «в одно жало» — его занимал
  iPhone, и колонка не могла поднять сессию вообще. Car Thing — коммутатор.
- **Свой L2CAP-сервер на AVCTP PSM** вместо `Protocol.listen()`: каждое входящее
  соединение получает отдельную сессию; маршрутизация по trust
  (`_on_avrcp_session_start`): источник → мониторы, колонка → backchannel.
- **L2CAP mode negotiation (vendored Bumble)**: на запрос не-Basic режима
  (Fosi просит ERTM на AVCTP) отвечать Configure Response
  `UNACCEPTABLE_PARAMETERS` с контрпредложением Basic — peer повторяет Configure
  и канал открывается. ABORT при mode mismatch ЗАПРЕЩЁН — он молча убивал AVCTP
  Fosi во всех прошлых тестах. Защищено в `scripts/check-bumble-vendor.py`.
- **Право первой инициативы пиру**: `ensure_speaker_avrcp` ждёт 3 c после старта
  аудиоканала (Fosi открывает AVCTP сам через ~0.2 c; встречный connect даёт
  L2CAP-коллизию mode mismatch — run11).
- **Backchannel подключён**: `transfer.bridge.speaker_command_handler =
  backchannel.handle_speaker_command` в carthing_runtime. Без этой строки
  команды колонки умирают в логе.
- Атрибуция: ВСЕ AVRCP-логи содержат `peer=<адрес>`. Логи без атрибуции стоили
  двух ложных выводов за одну ночь.

Evidence: artifacts/dual-mode-tests-20260610/ run11 (коллизия), run12 (ERTM
abort), run13 (двойная сессия + рабочий backchannel).

---

## ADDENDUM 2026-06-10 (день, громкость) — семантика громкости маршрута

Доказанные правила (НЕ ломать):

- **Источник — хозяин громкости маршрута.** iPhone задаёт громкость
  (absolute volume), мост коалесцированно пишет её в колонку
  (`SetAbsoluteVolume`, успех для CONTROL-команд = `ResponseCode.ACCEPTED`,
  `Protocol._check_response` Bumble годится ТОЛЬКО для STATUS-команд).
- **Целиться в активный приёмник маршрута** (`receiver_address`), НЕ в
  `default_speaker_address()` из реестра — там первым может стоять виртуальный
  выход Car Thing с пустым адресом (тихий обрыв форварда).
- **Interim-значение громкости колонки при регистрации — съедать.** Это её
  сохранённое состояние, не действие пользователя; форвард его в источник
  затирал громкость iPhone лежалым значением (50% → 93).
- **iOS помнит громкость ПЕР-МАРШРУТНО.** «Прыжок» громкости при выборе
  Car Thing в Control Center — это iOS восстанавливает запомненный уровень
  этого маршрута (он приходит ОТ iPhone, в логе `absolute volume=N peer=10:…`).
  Это штатно и самоизлечивается — НЕ чинить на нашей стороне.
- **ZD3: громкость пульта в BT не экспортируется** — доказано 4 механизмами
  AVRCP + независимым эталоном (родной стек macOS, poll 2/с, ноль трафика).
  У колонки два независимых тракта громкости. Машинерия Fosi→iPhone
  (принудительная подписка на VOLUME_CHANGED вопреки capabilities + notify в
  сессию источника + эхо-гашение через единую route-громкость) ОСТАВЛЕНА в
  коде — работает с любой колонкой, которая честно нотифицирует.
- Приём «подписка вопреки заявленным capabilities» — рабочий: ZD3 врёт в
  GetCapabilities (не заявляет VOLUME_CHANGED), но регистрацию принимает.

---

## ADDENDUM 2026-06-10 (вечер) — стек ЗАПЕЧЁН в rootfs

Бандл `flash-bake-unified-stable-20260610-130003` (rootfs sha256 `57312f12…`,
runtime tree `519e6d47…`) прошит rootfs-only @sector 352256. Boot-цепочка и
p1-раздел (keystore/state) не тронуты — бонды переживают прошивку и ребут.
Проверено живой загрузкой: весь коммутатор (Fosi standby+stream+AVRCP,
iPhone BLE+classic+AVRCP) поднимается из `/usr/lib/carthing` одной командой
(lab-override, карантин действует). Автостарт НЕ включён — снятие карантина
требует отдельного решения владельца (см. ADDENDUM 2026-06-04 про карантин).
Команда запуска после любого ребута:

```sh
ssh root@172.16.42.77 'cd /usr/lib/carthing && env CARTHING_BUMBLE_QUARANTINE=0 \
  CARTHING_ALLOW_BUMBLE_RUN=1 CAR_THING_TRANSPORT=hci-socket:0 \
  CAR_THING_KEYSTORE=/run/carthing-state/carthing/keys.json \
  CAR_THING_LIB=/usr/lib/carthing/vendor CARTHING_GUI_ENABLE=0 \
  CARTHING_CLASSIC_AUDIO_RECONNECT=1 nohup python3 -B carthing_runtime.py \
  > /run/carthing/carthing-runtime.log 2>&1 &'
```

---

## ADDENDUM 2026-06-10 (вечер) — КАРАНТИН BUMBLE СНЯТ решением владельца

Стек валидирован (см. таблицу dual-mode-test-plan) и запечён → автостарт включён:
- `/etc/init.d/S60-carthing-runtime` — supervisor-петля (respawn 5 c), дефолтный
  режим Play Now (classic только по тумблеру `/run/carthing/route-cmd`);
- `/etc/default/carthing`: `CARTHING_BUMBLE_QUARANTINE=0`, `ALLOW_BUMBLE_RUN=1`;
- **аварийный рубильник без перепрошивки**:
  `touch /run/carthing-state/carthing/no-autostart && reboot`;
- имя `S50-carthing-remote` ПО-ПРЕЖНЕМУ запрещено (этот запрет не снят).

---

## ПОПРАВКА к ADDENDUM о снятии карантина (2026-06-10, вечер)

Реальный автостарт оказался НЕ S60: настоящий стартер — цепочка
**inittab → rcS/init-wrapper → `/etc/init.d/disabled-S50-carthing-remote`**
(init-wrapper вызывает его ПО ИМЕНИ; имя обманчиво — скрипт активный, его
гейтом был карантин в /etc/default/carthing). После снятия карантина он и
запускает runtime с полным продуктовым env-контрактом + supervisor-петля
(respawn 4 c, pid-файл /run/carthing/media-remote-supervisor.pid).

- S60-carthing-runtime УДАЛЁН (ошибочный дублёр; внесён в RETIRED_INIT_FILES).
- Аварийный рубильник вшит в настоящий стартер:
  `touch /run/carthing-state/carthing/no-autostart && reboot`.
- Комментарий в скрипте исправлен — больше не врёт про «manual entry point only».

⚠️ Урок: state.json потерял Fosi-строку (trusted_speakers=0 после ребута) —
восстановлена штатным enrollment'ом (`AppState.enroll_trusted_device` с
audio_sink). ПРИЧИНА НЕ УСТАНОВЛЕНА — наблюдать; кандидат: миграция/перезапись
state при стартах эпохи A3-циклов.
