# Хэндофф Codex'у — sticky-реконнект iPhone (диагноз от Claude, 2026-06-01)

## TL;DR
«Не прилипает к iPhone». Первичная пара проходит и шифруется НОРМАЛЬНО, бонд персистится.
Ломается **возобновление шифрования при РЕКОННЕКТЕ**. Корень найден и подтверждён HCI-трейсами:
**resolving list (RPA→identity) грузится только в `Device.power_on()` из keystore; бонд, созданный
ПОСЛЕ старта, в резолвер не попадает → RPA телефона не резолвится → Bumble не находит LTK →
`HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY` → нет шифрования.** Вторично: при ВКЛЮЧЁННОМ
резолвинге iPhone вообще перестаёт коннектиться (privacy/адрес рекламы на этом BCM-контроллере).
Это твой слой (BLE/прошивка, ты рефлешил) — отсюда хэндофф.

## Состояние сейчас (я всё откатил)
- `accessory_orchestrator.py` и `carthing_runtime.py` — возвращены к ТВОЕЙ committed-версии (git HEAD).
- Устройство перепрошито этими же файлами + рантайм перезапущен = твой чистый baseline.
- `keys.json` содержит ВАЛИДНЫЙ свежий бонд (см. ниже) — НЕ удалял, фундамент рабочий.
- Моих правок в рантайме НЕТ. В дереве только untracked `tools/carthing-mcp/` (read-only MCP, рантайма не касается).
- Временный DEBUG, которым снимал трейсы, тоже убран.

## Что наблюдалось

### 1) Первичная пара (через меню «режим сопряжения») — РАБОТАЕТ
```
connected: 68:02:C9:39:F1:5B classic=False encrypted=False
requesting pairing (link not encrypted yet)
bumble.smp: pairing method: JUST_WORKS
... DHKEY_CHECK expected==got ...
HCI_LE_LONG_TERM_KEY_REQUEST_EVENT → HCI_LE_LONG_TERM_KEY_REQUEST_REPLY (ltk=acf740…)
*** Connection Encryption Change: ... encryption=1
AMS start (encryption) → AMS: ready
SMP_IDENTITY_INFORMATION + SMP_IDENTITY_ADDRESS_INFORMATION (обе стороны раздали IRK)
pairing complete → phase=le_ready_needs_classic
```
Т.е. устройство раздаёт СВОЙ IRK телефону, телефон раздаёт свой (identity `10:A2:D3:83:82:50/P`).

`keys.json` после пары (namespace "CarThing"):
```json
{ "CarThing": { "10:A2:D3:83:82:50/P": {
    "address_type": 0, "irk": {"value":"1580b713deabea59e3de1c62e4e4db21"},
    "ltk": {"value":"acf740e8c7d5eb1dd9f1e50fed88c0e1"} } } }
```

### 2) Реконнект под ТВОЕЙ sticky (`PUBLIC` + `filter 0x00` + directed-burst) — НЕ ШИФРУЕТСЯ
```
connected: 7F:BA:6C:5A:65:3A (новый RPA телефона) encrypted=False
SMP_SECURITY_REQUEST_COMMAND  (устройство просит зашифровать)
HCI_LE_LONG_TERM_KEY_REQUEST_EVENT
HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY_COMMAND   ❌  ← Bumble не нашёл LTK
peer_resolvable_private_address: 00:00:00:00:00:00     ← резолвинг RPA не отработал
→ нет encryption_change, нет AMS, линк рвётся. «Не прилипает».
```

## Корень (с привязкой к bumble/device.py на устройстве, `/usr/lib/carthing/vendor/bumble/device.py`)
- `get_long_term_key()` (~стр.1732): берёт `keys = await self.keystore.get(str(connection.peer_address))`.
  Чтобы нашлось — `connection.peer_address` должен быть IDENTITY (`10:A2…`), а не RPA.
- На коннекте (~стр.1966-1972): `if self.address_resolver: resolved = address_resolver.resolve(peer)` —
  RPA→identity делается ТОЛЬКО если есть `self.address_resolver`.
- `self.address_resolver` и resolving list создаются ТОЛЬКО в `power_on()` (~стр.918-944):
  `resolving_keys = await self.keystore.get_resolving_keys()` → `HCI_LE_Add_Device_To_Resolving_List`
  → `HCI_LE_Set_Address_Resolution_Enable(1)` → `address_resolver = smp.AddressResolver(resolving_keys)`.
- Значит: **если бонд создан ПОСЛЕ power_on (как при паре в рантайме), резолвер пустой и не
  обновляется.** На реконнекте активной SMP-сессии нет → `smp_manager.get_long_term_key` = None →
  keystore.get(RPA) = miss → NEGATIVE_REPLY.

### Подтверждение «на другой стороне»
После рестарта рантайма, когда бонд УЖЕ был в `keys.json`, на `power_on` в логе появились:
```
HCI_LE_CLEAR_RESOLVING_LIST_COMMAND
HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST_COMMAND     ← IRK телефона загружен
HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE: 1         ← резолвинг включён
```
То есть при наличии бонда на старте резолвер грузится корректно. Раньше «прилипало годами»
именно потому, что после пары был ребут, и на следующем power_on resolving list поднимался.

## Вторая проблема (всплыла, когда резолвинг включился)
С `address_resolution_enable=1` (бонд был на старте) iPhone **вообще перестал инициировать
коннект** (≈2 мин, toggle BT + lock/unlock — ноль `connected:`). А РАНЬШЕ (резолвинг выкл) телефон
коннектился (но падал на LTK). Гипотеза: на этом BCM-контроллере включение address resolution
меняет адрес/форму рекламы (own_address_type=PUBLIC + локальный IRK), и iPhone перестаёт узнавать
устройство как своё bonded. Это контроллер/прошивка — твой рефлеш-домен.

**Тупик из userspace:** резолвинг OFF → коннект есть, LTK нет; резолвинг ON → LTK есть, коннекта нет.

## Гипотезы фикса (тебе решать — это твой слой)
1. **Refresh resolving list после пары** (`orch.on_bonded` / после `_iphone.setup`): повторить блок
   power_on (clear resolving list → add из `keystore.get_resolving_keys()` → enable → пересоздать
   `device.address_resolver`), чтобы реконнект работал в ТОЙ ЖЕ сессии без рестарта. В Bumble нет
   публичного `refresh_resolving_list` — но логику power_on можно вызвать повторно/вынести.
2. **Согласовать адрес рекламы под включённый резолвинг**, чтобы iPhone узнавал устройство:
   - либо стабильно рекламировать IDENTITY/public;
   - либо `own_address_type=RESOLVABLE_OR_PUBLIC` для пары И sticky (тогда устройство в эфире — RPA,
     который iPhone резолвит по device-IRK, розданному на паре). Проверить, что контроллер реально
     отдаёт пригодный адрес при resolution=1.
3. **directed-burst в `kick_reconnect`** — directed-к-identity приватный iPhone (RPA) игнорирует;
   старый media_remote это сознательно не делал. Похоже, бесполезен и добавляет 4с задержки.
4. **Cold-boot аспект** (который ты рефлешил) проверить отдельно: резолвинг+реклама именно на
   холодном старте.

## Что я менял за сессию (и откатил)
- Пробовал откат sticky на `RESOLVABLE_OR_PUBLIC + 0x03 nameless` — iPhone не коннектился (бонд был
  сформирован под PUBLIC) → откатил.
- Чистил `keys.json` и делал свежую пару (она прошла, см. выше). Бонд валиден.
- Временно поднимал DEBUG для снятия HCI-трейсов → убрал.
ИТОГ: всё вернул к твоему baseline. Трогать этот узел дальше не стал — он твой (BLE/прошивка).
```
Спасибо. — Claude
```

## ДОПОЛНЕНИЕ (после тестов пользователя, 2026-06-01)

### Эмпирическое ПОДТВЕРЖДЕНИЕ диагноза
После моего финального рестарта (бонд УЖЕ был в keys.json на старте → resolving list загрузился):
пользователь вручную подключил → подключилось (медленно); затем BT off 10-15 мин → on →
**АВТО-реконнект сработал.** То есть при наличии бонда на `power_on` всё ПРИЛИПАЕТ. Ломается только
окно «пара → реконнект БЕЗ рестарта» (резолвер не обновляется после пары). Фикс №1 (refresh
resolving list на on_bonded) закрывает именно это окно.

ПОПРАВКА к моему прежнему выводу: «резолвинг ON → iPhone не коннектится» — НЕВЕРНО, это была просто
ленивая/долгая логика реконнекта iOS (я ждал лишь ~2 мин; на 10-15 мин он сам подключается).
«Долго думает» = нормальная латентность BLE-HID реконнекта iOS (+ возможно +4с directed-burst).

### Асимметрия бонда при «забыть на iPhone» (НЕТ device-side forget)
В BLE нет over-the-air unbond. «Забыть» на iPhone стирает ключи только на iPhone; устройство НЕ
уведомляется и держит свои ключи → асимметрия. В рантайме НЕТ device-side forget (grep пусто),
хотя `bumble.keys.KeyStore` умеет `delete`/`delete_all`. Само-лечится пере-парой (новая пара для той
же identity перезаписывает: видели LTK 4fe161…→acf740…). НУЖНО: «Забыть устройство» в
Settings→Доверенные → `keystore.delete(addr)` + refresh resolving/accept-list. Иначе протухший
ключ висит и даёт «iPhone коннектится, но шифрования нет» до пере-пары.

### Предлагаемая тест-матрица
1. пара → ребут устройства → реконнект: ожид. ПРИЛИПАЕТ.
2. пара → БЕЗ ребута → реконнект: ожид. НЕ прилипает (до on_bonded-refresh).
3. forget на iPhone (без пере-пары) → keys.json: ключ остался (асимметрия).
4. forget → пере-пара → keys.json: LTK перезаписан, одна запись (само-лечение).
5. долгий BT-off → латентность авто-реконнекта.
6. холодное устройство → старт → коннект (firmware cold-boot, твой рефлеш-домен).

## РЕАЛИЗОВАНО И ПРОВЕРЕНО ВЖИВУЮ (Claude, 2026-06-01) — авто-пере-пара после forget

Проблема «forget на iPhone → не пере-парится»: при включённом address-resolution (загружен на
power_on из старого бонда) контроллер резолвит RPA новой пары в СТАРУЮ identity → device берёт
identity-адрес в SC-крипто, iPhone — свой RPA → DHKey check НЕ сходится → SMP_DHKEY_CHECK_FAILED.

Сделал ДВА фикса (оба помечены `[CLAUDE 2026-06-01]`, оба задеплоены и проверены на железе):
1. ПРОАКТИВНЫЙ — `accessory_orchestrator.arm_pairing(on=True)`: при входе в режим сопряжения
   `_disable_resolution_for_pairing()` (stop adv → `HCI_LE_Set_Address_Resolution_Enable(0)` +
   `HCI_LE_Clear_Resolving_List`). Первая SC-пара идёт на on-air RPA с обеих сторон → DHKey сходится
   → **пара с ПЕРВОГО раза**. Свежая пара перезаписывает старый бонд (keystore keyed by identity).
2. РЕАКТИВНЫЙ бэкстоп — `carthing_runtime._on_connection` хэндлер `pairing_failure`: если пара всё
   же упала, авто `keystore.delete_all()` + clear/disable resolving → iPhone сам реконнектит и
   пара проходит на ретрае.

Лог-подтверждение (первая попытка):
```
Pairing mode: address resolution OFF (clean first-try pairing)
connected 10:A2… → requesting pairing → AMS start (encryption) → AMS: ready   (БЕЗ DHKEY_FAILED)
```

ОСТАВШИЙСЯ КАВEAT (твой долгосрочный фикс №1): после пары резолвинг ВЫКЛЮЧЕН до следующего
power_on. Sticky-реконнект в той же сессии не резолвит LTK, пока не перезагрузишь устройство
(power off/on — у пользователя работает). Чисто закрывается через **refresh resolving list на
`on_bonded`** (re-enable resolution с новым бондом сразу после пары) — тогда рестарт не нужен.

ДОБАВЛЕНО device-side «забыть» (косвенно): пере-пара теперь перезаписывает бонд автоматически.
Явного пункта «Забыть устройство» в Settings всё ещё нет (см. выше) — это к тебе.
