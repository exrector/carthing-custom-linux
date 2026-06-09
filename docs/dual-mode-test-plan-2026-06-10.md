# Dual-Mode → полный маршрут iPhone → Car Thing → Fosi: тест-ранбук

Дата: 2026-06-10. Исполнитель: Codex. Владелец подтверждает шаги, требующие
действий на iPhone (Forget/pair/play) и слуховую проверку Fosi.

Цель: от доказанного результата 2026-06-05 (iPhone публикует Car Thing в Control
Center и стримит AAC RTP) дойти до полного желаемого результата:

1. музыка с iPhone реально звучит из Fosi через трубу Car Thing;
2. AVRCP работает в обе стороны и для обоих пиров;
3. всё это переживает перезагрузку и штатно реконнектится;
4. чистая первая пара воспроизводима без гонок;
5. поведение соответствует официальным Apple Accessory Design Guidelines (ADG).

---

## 0. Рамки — читать до первого действия

- **Перед стартом прочитать `INVARIANTS.md` целиком.** Ни один тест не имеет
  права ломать пункты 1–7 и аддендумы. Если шаг противоречит инварианту —
  остановиться и спросить владельца.
- Bumble в карантине: любой запуск runtime только как lab-override
  `CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 <command>`
  из `/run/carthing-dual-mode-lab`. Имя `S50-carthing-remote` в образ не возвращать.
- **Одно изменение переменной за тест.** Урок 2026-06-05: несколько изменений
  профиля за раз делают результат неинтерпретируемым.
- Девайсы: iPhone `10:A2:D3:83:82:50`, Fosi Audio ZD3 `C4:A9:B8:70:2F:E5`,
  Car Thing `root@172.16.42.77` (если VPN utun ломает маршрут — `route add` перед SSH).
- Чистая пара: `tools/reset_dual_mode_pairing_test.sh` + ручной «Forget This Device»
  на iPhone. **Не чистить keys.json без необходимости** — большинство тестов ниже
  обязаны переиспользовать существующий бонд (это само по себе проверка).
- Evidence: каждый тест пишет лог в
  `artifacts/dual-mode-tests-20260610/<TEST-ID>.log`, по завершении блока —
  обновить `SHA256SUMS`. Результат заносить в таблицу в конце этого файла
  (**только дописывать**, не переписывать).
- После каждого зелёного теста, потребовавшего правку кода, — git commit
  (без переписывания истории).

**Шаг 0 (до любых тестов): закоммитить staged-прорыв 2026-06-05.**
В индексе ~960 строк (flush-фикс, classic-first CTKD, AVRCP handshake, доки).
Это доказанная работа, она не должна жить uncommitted.

---

## 1. Доказанная база — НЕ перепроверять, НЕ ломать

Зафиксировано 2026-06-05 (`artifacts/dual-mode-20260605/dual-mode-flush-fix-success.log`):

```text
dual-mode host enabled: LE + Classic + simultaneous + SMP/CTKD
A2DP_SOURCE_OPEN codec=AAC
A2DP_SOURCE_RTP_OPEN codec=AAC
AVRCP target absolute volume=56
A2DP_SOURCE_START codec=AAC
A2DP_BRIDGE_RTP
```

Единая пара (ltk+irk+link_key в одной записи), CTKD/CT2, classic-активация
публикует Car Thing в Control Center автоматически. Если какой-то тест ниже
ломает эти маркеры — тест немедленно красный, изменение откатывается.

---

## Блок A — фиксы по findings ревью Codex 2026-06-05

Это пре-реквизиты трубы. Порядок: A3 → A1 → A2 (High), затем A4–A6.

### A1 (High) — согласование кодеков входа и выхода

Сейчас: вход предлагает AAC+SBC (`a2dp_bridge.py:1203`), выход выбирает
независимо с приоритетом AAC (`a2dp_bridge.py:604`), RTP пересылается без
изменений (`a2dp_bridge.py:1310`). Mismatch = битый поток в Fosi.

Варианты (пробовать по порядку, остановиться на первом рабочем):

- **A1a — конфиг-копирование**: при `A2DP_SOURCE_SET_CONFIGURATION` от iPhone
  переконфигурировать исходящий endpoint к Fosi тем же кодеком и теми же
  Codec Specific Information Elements. Если Fosi не умеет этот кодек —
  см. A1b.
- **A1b — пересечение возможностей**: до открытия входа узнать кодеки Fosi
  (capability discovery, см. идею «device cards» в ideas-log), и предлагать
  iPhone только пересечение. Если у Fosi нет AAC — предлагать iPhone только SBC.
- **A1c — транскодирование** (резерв): принять AAC, декодировать, кодировать SBC.
  Проверить CPU-бюджет на S905D2 до реализации. Делать только если A1a/A1b
  невозможны.

Тест-матрица: (iPhone=AAC, Fosi=AAC), (iPhone=SBC, Fosi=SBC), и негативный —
убедиться что mismatch теперь невозможен (в логе кодеки входа и выхода совпадают).

### A2 (High) — AVRCP на каждого пира + рабочий Fosi-backchannel

Сейчас: один `avrcp.Protocol` (`a2dp_bridge.py:253`), любой активный AVCTP
считается «нужным» (`a2dp_bridge.py:1055`), Bumble закрывает второе подключение
(`vendor/bumble/avrcp.py:2218`), команды Fosi только логируются (`a2dp_bridge.py:62`).

Фикс: экземпляр AVRCP на соединение, маршрутизация по BD_ADDR;
команды от Fosi (pause/play/next с кнопок колонки) пробрасывать в
`TransferControlBackchannel` → iPhone.

Тест: при одновременных линках iPhone+Fosi (а) absolute volume от iPhone
по-прежнему приходит, (б) нажатие play/pause на Fosi реально ставит iPhone
на паузу, (в) ни один из двух AVCTP не закрывается.

### A3 (High) — гонка classic-first CTKD с сохранением Link Key

Сейчас: CTKD стартует сразу после encryption (`carthing_runtime.py:716`), а
Link Key сохраняется асинхронно (`vendor/bumble/device.py:5593`); SMP падает
если ключа ещё нет (`vendor/bumble/smp.py:1107`).

Фикс: дождаться завершения persistence (await/event) или ретрай чтения keystore
с коротким backoff до старта CTKD.

Тест: 5 чистых classic-first пар подряд (каждая: reset-скрипт + Forget) —
ноль `CROSS_TRANSPORT_KEY_DERIVATION_NOT_ALLOWED`, в keystore каждый раз
ltk+irk+link_key одной записью.

### A4 (Medium) — открытый ACL становится trusted source после CTKD

Фикс: callback завершения CTKD (`carthing_runtime.py:700`) должен дорегистрировать
текущее соединение как источник (registry + `_source_connection`), чтобы
`disconnect_source()` работал без перезапуска.

Тест: после чистой classic-first пары, не перезапуская runtime,
`disconnect_source()` штатно рвёт линк; источник виден в registry.

### A5 (Medium) — reconnect выбирает полноценный dual-mode бонд

Фикс: `carthing_runtime.py:156` — предпочитать источник, у которого в keystore
одновременно LTK и Link Key, а не первую запись.

Тест: добавить в trusted BLE-only запись (MacBook) первой — reconnect всё равно
идёт к iPhone с полным бондом.

### A6 (Medium) — честный CTKD-чекер

Фикс: `scripts/check-bumble-vendor.py:63` — прогонять реальную
`AccessoryOrchestrator.pairing_config_factory` и направления key distribution,
а не синтетический `PairingConfig(ct2=True)`.

Тест: временно сломать CTKD в runtime-конфиге → чекер обязан упасть; вернуть → зелёный.

---

## Блок B — труба iPhone → Car Thing → Fosi (главная цель)

Опора: INVARIANTS п.2 (Fosi-бонд эталонный, не перенастраивать) и п.3
(труба работала 2026-06-04, `sent_to_speaker=True`; условие — канал к Fosi
открыт ДО старта стрима iPhone, одно радио).

- **B1 — базовый сценарий (после A1, A2):** существующая пара; standby-канал к
  Fosi открыт (`A2DP stream opened+held`); classic-активация iPhone; владелец
  включает музыку. Успех: маркеры базы из §1 + `A2DP_BRIDGE_RTP` +
  `sent_to_speaker=True` + **владелец слышит звук из Fosi**.
- **B2 — обратный порядок (диагностика):** iPhone уже стримит, потом поднимать
  Fosi-канал. Ожидаемо хрупко (page сквозь насыщенное радио, `TimeoutError`).
  Зафиксировать фактическое поведение — это вход для блока F.
- **B3 — кодек-матрица:** B1 при AAC→AAC и при SBC→SBC (форсировать через A1b
  выбор). Сравнить стабильность/качество.
- **B4 — AVRCP сквозной:** во время B1 — pause/play с кнопок Fosi, absolute
  volume с iPhone, track change. Всё отражается корректно, труба не рвётся.
- **B5 — перерывы потока:** пауза 30 с → resume (iOS может слать
  AVDTP_Suspend — труба обязана пережить); Siri поверх музыки; входящий
  звонок (HFP у нас нет — зафиксировать, как iOS маршрутизирует звонок и
  возвращается ли музыка в трубу после).
- **B6 — выход из радиуса:** унести iPhone до разрыва, вернуться. Реконнект
  без действий пользователя, труба восстанавливается (с учётом A5).

---

## Блок C — рычаги из Apple Accessory Design Guidelines

Источник: официальный PDF `developer.apple.com/accessories/Accessory-Design-Guidelines.pdf`
(ревизия 2026-06-08; локальная копия в репо:
`reference/apple-adg/Accessory-Design-Guidelines-2026-06-08.pdf` + извлечённый текст `.txt` рядом).
Каждый пункт — отдельное изменение + отдельный тест.

### C1 — ServiceDatabaseState: убить вечный «Forget This Device» ⭐

ADG 57.11.2: аксессуар **shall** поддерживать `ServiceDiscoveryServer` service
class и атрибут `ServiceDatabaseState`, значение которого меняется при любом
изменении SDP-записей. Именно через него iOS инвалидирует свой SDP-кэш.
Наша главная боль («iOS кэширует SDP → forget + переспара после каждой правки»,
INVARIANTS п.7) может быть следствием отсутствия этого атрибута.

Реализация: добавить SDP-запись ServiceDiscoveryServer (0x1000) с
`ServiceDatabaseState (0x0201)`; инкрементировать значение при каждой установке/
смене наших A2DP/AVRCP/DID записей.

Тест: на существующей паре изменить видимый SDP-параметр (например,
SupportedFeatures), инкрементировать state, переподключиться **без forget** —
проверить (логом SDP-запросов от iPhone), что iOS перечитала записи.
Если работает — все последующие SDP-тесты ускоряются на порядок.

### C2 — Device ID Profile (DID) 1.3+

ADG 57.11.1: аксессуар **shall** поддерживать DID. Добавить SDP-запись
PnPInformation (0x1200): VendorID (не Apple!), ProductID, Version,
VendorIDSource. iOS использует DID для обхода кривых реализаций — отсутствие
записи может влиять на отношение стека к аксессуару.

Тест: запись видна в SDP; чистая пара + Control Center не регрессируют.

### C3 — EIR: Local Name + TX Power Level

ADG 57.5: EIR **shall** содержать Local Name и **TX Power Level**.
Проверить текущий EIR (имя есть — инвариант 5; TX Power, вероятно, нет) и
дополнить. Имя без `:`/`;`.

### C4 — Sniff mode

ADG 57.3: аксессуар **shall** принимать sniff-запросы устройства с любыми
валидными параметрами, без ренеготиации; поддерживать интервал 15 ms и sniff
subrating. Проверить, как vendored Bumble отвечает на
`HCI_Sniff_Mode`/`HCI_Sniff_Subrating` от iPhone (в логах 2026-06-05 поискать
mode change events). Если отклоняем — это кандидат на причину нестабильности
длинных сессий и лишний расход радио (важно для трубы: одно радио на два линка).

### C5 — Role Switch и Link Supervision Timeout

ADG 57.4: **shall** принимать Role Switch запросы; не настаивать на Central.
ADG 57.9: когда мы Central — link supervision timeout ≥ 2 s.
Для трубы мы Central к Fosi и Peripheral к iPhone (scatternet) — проверить,
что Bumble принимает role switch от iPhone и что таймаут к Fosi ≥ 2 s.

### C6 — AVDTP тайминги: RTX_SIG_TIMER = 5 секунд

ADG 53.1.1: отвечать на AVDTP-транзакции до истечения 5-секундного
RTX_SIG_TIMER устройства, иначе iOS рвёт signaling. Аудит наших логов: все
ответы на AVDTP-команды iPhone < 5 s (особенно под нагрузкой трубы).
Загадка «iPhone закрывал AVDTP через ~10 s после OPEN» уже решена (flush),
но таймер остаётся жёстким требованием при деградации.

### C7 — параметры кодеков по таблицам Apple

ADG Table 53-1 (SBC): 16/32/44.1/48 kHz, Stereo, Block 16, Subbands 8,
Loudness, **bitpool 2–53, поддерживать 53**.
ADG Table 53-2/53-3 (AAC-LC): MPEG-2 AAC LC, VBR=1, bitrate до 264 630 bps,
**минимум 96 kbps при VBR**, LATM/RFC 3016, **рекомендованный L2CAP MTU 885**,
один AudioMuxElement на AVDTP-пакет, переживать смену битрейта без пропусков.
Сверить наши endpoint capabilities с этими таблицами; расхождения — править.

### C8 — Delay Reporting в рамках

ADG 57.10: задержка ≤ 1000 ms, обновления не чаще 1/с. Delay Reporting уже
принят 2026-06-05 — проверить, что наши значения/частота в рамках.

### C9 — AVRCP-поведение

ADG 57.11.5.3: регистрироваться на нотификации, **не поллить** статус.
ADG 57.11.5.4: перед отправкой Play/Pause подтверждать статус устройства
по нотификации (важно для кнопок Fosi → iPhone в A2).
ADG 57.12.2.1: `EVENT_PLAYBACK_STATUS_CHANGED=Play` отличает музыку от
system sounds — использовать как сигнал «реальный поток» для
`source_stream_active` (а это уже завязано на авто-forget из INVARIANTS п.1).

### C10 — CoD (только как зафиксированная опция, БЕЗ самовольной смены)

ADG 57.8 приводит пример: car-audio для автомобильного аксессуара
(minor class car-audio = CoD `0x240408`). Наш инвариант — `0x240414`
(loudspeaker), доказан рабочим. **Не менять.** Записано как вариант на случай,
если когда-либо понадобится поведение «автомагнитолы» в iOS — только с явного
решения владельца и отдельным чистым first-pair тестом.

---

## Блок D — персистентность и перезагрузки

- **D1 — bake:** после зелёных A+B: `scripts/check-bumble-vendor.py` →
  `scripts/bake-unified-runtime-rootfs.py` → стандартная прошивка
  (`scripts/flash-device1-rootfs-only.py`, бандл по образцу
  `artifacts/flash-python-full-final-20260605/`). Lab-override в образ не печь
  (карантин остаётся инвариантом — runtime поднимается своим штатным путём).
- **D2 — reboot-матрица** (каждый пункт: труба восстанавливается, Control
  Center показывает Car Thing, без действий пользователя кроме play):
  1. ребут Car Thing;
  2. Bluetooth off/on на iPhone;
  3. ребут iPhone;
  4. power-cycle Fosi;
  5. ребут Car Thing при играющей музыке (поток на iPhone не «зависает» навсегда);
  6. холодный старт всех трёх.

---

## Блок E — стресс и краевые случаи (после D)

- 10 циклов connect/disconnect подряд — без деградации.
- Непрерывный стрим 30+ минут — без дропов (смотреть RTP-счётчики и слух).
- iPhone засыпает с играющей музыкой / будится.
- Второй источник: MacBook подключается, пока iPhone в трубе — поведение
  предсказуемо, труба iPhone не рвётся (или рвётся по явной политике).
- Громкость 0% и 100% (absolute volume edge).

---

## Блок F — радио-ресурс (если труба нестабильна на одном чипе)

Резервные рычаги, по одному, только при доказанной нестабильности B:

- F1 — локальная flush-политика к Fosi: `HCI_Write_Automatic_Flush_Timeout_Command`
  уже реализован и протестирован на сериализацию — применить **к локальному
  отправителю на Fosi-линке** (правильное направление!), чтобы устаревшие
  аудио-пакеты не копили очередь радио.
- F2 — sniff на простаивающем линке (после C4): меньше airtime — больше окна
  второму линку.
- F3 — роли: убедиться, что мы Peripheral к iPhone и Central к Fosi; не
  инициировать role switch сами (C5).
- F4 — приоритезация ACL: проверить, даёт ли HCI vendor-канал чипа управление
  приоритетами линков (только чтение документации/осторожный эксперимент).

---

## Отдельная дорожка (НЕ в этом ранбуке)

iAP2/MFi поверх `/dev/apple_mfi` — по инварианту 2026-06-04 не включать в
аудио-baseline (`CARTHING_IAP2_ENABLE=0`). Отдельный план после зелёного D.

---

## Порядок исполнения (сводно)

```
0  commit staged 2026-06-05
A3 → A1 → A2            # High-фиксы, открывают трубу
B1 → B3 → B4            # труба и управление
C1                       # ServiceDatabaseState — ускоряет всё дальнейшее
A4 → A5 → A6            # Medium-фиксы
C2 … C9                  # соответствие ADG, по одному
B5 → B6                  # перерывы и радиус
D1 → D2                  # bake + перезагрузки
E, F                     # стресс; F только при нестабильности
```

Стоп-правила: красный тест → откат изменения → запись в таблицу → следующий
вариант того же пункта (не следующий пункт). Любой конфликт с INVARIANTS.md —
остановка и вопрос владельцу.

---

## Таблица результатов (только дописывать)

| Дата | Тест | Вариант | Результат | Evidence | Комментарий |
|------|------|---------|-----------|----------|-------------|
