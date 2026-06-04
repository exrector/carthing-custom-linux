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
