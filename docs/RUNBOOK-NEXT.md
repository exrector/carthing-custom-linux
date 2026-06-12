# RUNBOOK-NEXT — план работ после сессии 2026-06-11 (Claude)

Самодостаточный документ для следующего агента (Codex/Claude) и владельца.
Контекст сессии 2026-06-11 не нужен — всё необходимое здесь и по ссылкам.

---

## 0. Состояние на конец 2026-06-11 (всё проверено владельцем на железе)

| Что | Статус | Коммит |
|---|---|---|
| Канонический деплой `tools/deploy` | ✅ работает | `a2e0413` |
| Тема «Терминал» (палитра exrector.com, IBM Plex Mono, CRT) | ✅ включена владельцем | `a0599e0` |
| Настройки: единые строки «− значение +» (5 ручек) | ✅ | `fca2f08`, `5004388` |
| Дубль iPhone в списке входов (стаб key="iphone") | ✅ убит | `5004388` |
| Труба iPhone→Fosi: suspend≠teardown ресивера + resume | ✅ музыка играет | `da4d6be` |
| Яркость: шкала панели инвертирована, ОБА края гасят экран | ✅ кламп [1,254] | `9318a48` + 2 фикса |
| [LNK] = только ПРИМЕНИТЬ выбранный маршрут (не toggle) | ✅ | `9318a48` |
| Boot-честность: после ребута выход = Play Now | ✅ | `9318a48` |
| Тап-флэш (обратная связь кнопок) | ✅ | `9318a48` |
| Кнопка настроек = тумблер (повторное нажатие закрывает) | ✅ | `fca2f08` |

**Git: всё закоммичено локально, ПУШ НЕ ДЕЛАЛСЯ (решение владельца «пушить потом»).**

---

## 1. ЖЕЛЕЗНЫЕ ПРАВИЛА (нарушение = угробить проект)

1. **Перед ЛЮБОЙ правкой BT/transfer/route — прочитать `INVARIANTS.md`** в корне репо.
   Особенно: classic discoverable=False ВСЕГДА; keys.json не чистить; suspend ≠ teardown.
2. **Деплой ТОЛЬКО через `tools/deploy`** (из корня репо):
   `tools/deploy usr/lib/carthing/<файл> [--restart]`. Никаких scp/sftp — macOS scp
   МОЛЧА фейлится (нет sftp-server). Подробности: `docs/file-delivery.md`.
3. **py_compile НЕ ловит NameError.** После правки модуля — smoke-импорт:
   `python3 -c "import <module>"` в каталоге overlay/usr/lib/carthing (кейс: забытый
   `import os` положил весь GUI, лечили в рантайме).
4. **Подсветка панели**: шкала инвертирована, raw 0 И raw 255 = чёрный экран.
   Весь код яркости ходит через `power_policy._write_brightness` (инверсия + кламп).
   НЕ писать в sysfs brightness напрямую из нового кода.
   Аварийно при чёрном экране: `ssh carthing 'echo 1 > /sys/class/backlight/aml-bl/brightness; echo 0 > /sys/class/backlight/aml-bl/bl_power'`.
5. **Рестарт runtime**: kill PID валит и супервизор → поднимать
   `/etc/init.d/disabled-S50-carthing-remote` (идемпотентен). pkill на busybox НЕТ.
6. **Тема выбирается ПРИ ИМПОРТЕ ui_theme** (icon-defaults захватывают цвета).
   Живая мутация палитры невозможна. Смена темы = settings.set("ui_theme") + рестарт.
7. **Шрифт IBM Plex Mono ШИРЕ прежнего** — любые новые подписи проверять в превью
   (`CARTHING_UI_THEME=terminal python3 tools/ui_preview.py`), длинные лезут под «−»
   (кейс «Тема (перезагрузка)» → пришлось «Тема (рестарт)»).
8. **Build-том buildroot НЕ пересобирать ad hoc** — общий с другими агентами.
   Горячий деплой файлов поверх rootfs — предпочтительный путь.
9. **Слой системы / слой проекта не смешивать** — ничего проектного в flake/defconfig
   кроме уже добавленного gesftpserver.
10. **Не переписывать git-историю.** Только новые коммиты. Пуш — только по слову владельца.
11. **state.json / keys.json на устройстве не редактировать руками** при живом runtime —
    он перезапишет. Настройки меняются через GUI или через `settings.set()` в коде.

---

## 2. ⭐ ЗАДАЧА №1 — серия маршрутных тестов (приказ владельца)

Прогнать роутер с разными девайсами, отследить ВСЕ проблемы. На каждом шаге смотреть
лог: `ssh carthing 'tail -f /var/run/carthing/carthing-remote.log'`.

Маркеры здоровья:
- `A2DP_BRIDGE_RTP forwarded=N ... sent_to_speaker=True` — поток идёт;
- `forwarded=0 dropped=N sent_to_speaker=False` — труба «включена», но звука нет (БАГ);
- шторм `A2DP receiver connect failed ... 0x4` — нарушен suspend≠teardown (БАГ);
- `route incompatible ... no audio input endpoint` — мусор в списке входов (БАГ).

Сценарии (по порядку):
1. **Циклы [LNK]**: Fosi→[LNK]→музыка→Play Now→[LNK]→тишина→Fosi→[LNK]→музыка. ×5 подряд.
   Раньше второй цикл убивал AVDTP-сессию (0x4) — фикс `da4d6be` должен держать.
2. **Смена выхода под играющим источником**: музыка играет на Fosi → выбрать Play Now →
   [LNK] → музыка должна продолжиться на iPhone (труба вниз), GUI честный.
3. **Спящий iPhone**: заблокировать iPhone → [LNK] на Fosi. Ожидаемо: первый дозвон может
   упасть `PAGE_TIMEOUT`; повторный тап добивает. (См. задачу №4 — авто-ретрай.)
4. **Ребут под активным маршрутом**: маршрут играет → ребут Car Thing → после старта GUI
   обязан показать Play Now (boot-честность), труба поднята быть не должна; собрать заново.
5. **Вторая колонка** (если есть под рукой BT-колонка): спарить через [ADD], выбрать её
   выходом, [LNK]. Путь `_close_receiver_protocol` при СМЕНЕ колонки в бою не гонялся ни разу.
6. **Mac как источник** (если дойдут руки) — вход Mac, выход Fosi.

Результаты писать в `docs/route-test-series-results.md` (создать; только дополнять).

## 3. Задачи по приоритету (после тестов)

**№2 — BAKE.** Текущий rootfs устройства = последний bake (20260610-211451) + ГОРА горячих
деплоев. Всё живёт на персистентном rootfs и переживает ребут, НО прошивка с нуля потеряет
всё после `9e637ad`. Собрать свежий flash-bake (процедура — `full-flash-bake.py`, прошлые
артефакты `flash-bake-unified-stable-*`). В bake автоматически войдут vendor/PIL,
pillow.libs, IBMPlexMono, gesftpserver (defconfig) и все фиксы. После bake проверить
`scp`/`sshfs` (gesftpserver) и симлинк `/usr/libexec/sftp-server`.

**№3 — авто-ретрай connect_source.** При `PAGE_TIMEOUT` (iPhone спит) [LNK] требует второго
тапа. В `_apply_route_command("connect")` добавить 2–3 ретрая с паузой 3/6 c (паттерн ретраев
3/8/15 уже есть в коммите `fc2cb5e` — переиспользовать подход). НЕ ретраить бесконечно.

**№4 — GUI ретро-проход (остаток).** Сделано: транспорт RWD/PRV/PSE/NXT/FWD/FAV,
[SET][LNK][ADD][AST], стрелки скролла, тап-флэш. Осталось:
- дуга энкодера → фосфорные насечки (сейчас рисованная дуга);
- точки-индикатор десктопов → текст `< 1/3 >`;
- модал сопряжения и «Доверенные устройства» не прогнаны в терминальном стиле;
- блок-курсор/READY-строка — по вкусу владельца (обсудить, не делать молча).
Правки стиля — ТОЛЬКО в ui_theme/ui_components/ui_statusbar, логику экранов не трогать.
Каждую правку прогонять в превью ОБЕИХ тем (dark должна остаться нетронутой).

**№5 — «опрос состояния» маршрута.** Сейчас после ребута выход принудительно Play Now
(честный дефолт). Следующий уровень: GUI читает РЕАЛЬНОЕ состояние трубы
(transfer.bridge._source_connection, receiver streaming) и подсвечивает активный маршрут.
Идея владельца, обсуждена 2026-06-11. Не делать наспех — трогает route_planner/AppState.

**№6 — мелочи GUI:**
- значение «Сон» при выключенном сне можно показывать ярче (сейчас dim);
- превью settings_expanded: строки наезжают на нижний бар (артефакт превью-инструмента,
  на устройстве fullscreen — но поправить tools/ui_preview, чтобы не путал);
- лимит «Гашение ≥30 c» в set_off_after против новой шкалы сна в минутах — проверить
  согласованность (шкала шлёт секунды, всё ок, но min 30с позволяет 1 мин — норм).

**№7 — незакрытое из 2026-06-10** (см. `docs/session-2026-06-10-summary.md`):
A3 (гонка classic-first CTKD), C1 ServiceDatabaseState (Apple ADG), B6 (радиус),
SBC-ветка A1, загадка одного volume-шквала.

## 4. Как проверить, что ничего не сломал (чек-лист после каждого деплоя)

```sh
ssh carthing 'grep -E "GUI active|GUI disabled" /var/run/carthing/carthing-remote.log | tail -1'
ssh carthing 'grep -E "AMS: ready" /var/run/carthing/carthing-remote.log | tail -1'
ssh carthing 'grep -c Traceback /var/run/carthing/carthing-remote.log'
```
GUI active + AMS ready + 0 Traceback = базовая планка. Потом руками: яркость −/+,
[LNK] туда-обратно, уведомление с iPhone приходит.

## 5. Карта файлов (что где)

- `overlay/usr/lib/carthing/` — ВЕСЬ userspace (деплоится горячо):
  - `carthing_runtime.py` — вход, колбэки настроек/маршрута;
  - `a2dp_bridge.py` — труба, ресивер (suspend/resume!), AVRCP-коммутатор;
  - `app_state.py` — состояние, trusted-устройства, route_inputs/outputs;
  - `intents.py` — диспетчер интентов, display_adjust (единые −/+);
  - `screens.py` — экраны (DISPLAY_ADJUST, RouteBuilder, Settings);
  - `ui_theme.py` — ВЕСЬ стиль: палитры тем, шрифты, CRT-маска, иконки;
  - `ui_screen.py` — компоситор, тап-флэш, постэффекты на present;
  - `ui_statusbar.py` — нижний бар (терминальные RWD/PRV/...);
  - `power_policy.py` — подсветка (ИНВЕРСИЯ!), сон, тайминги рендера;
  - `gui_controller.py` — навигация, скролл, синк trusted.
- `tools/deploy` — канонический деплой; `tools/ui_preview.py` — превью на Mac.
- `docs/file-delivery.md` — матрица доставки файлов.
- Память агента: `~/.claude/projects/-Users-exrector/memory/` — carthing-* заметки,
  `carthing-route-test-series.md` = задача №1.

---
*Составлено Claude 2026-06-11 в конце сессии по просьбе владельца. Только дополнять.*

---

## Дополнение 2026-06-11: дизайн задачи №5 («опрос состояния» маршрута)

Модель: **desired vs actual** (reconciliation). Никакого опроса не нужно — все факты
у runtime уже есть, их надо лишь опубликовать и нарисовать.

**Слой 1 — выбор (desired):** что пользователь выделил в колонках ВХОД/ВЫХОД.
Уже есть: `route_input`/`route_output` флаги в AppState, персистятся.

**Слой 2 — факт (actual):** что реально стоит в радио. Источник правды —
`a2dp_bridge`, всё уже отслеживается:
- `_source_connection is not None` — classic-труба к iPhone поднята;
- `source_stream_active` — iPhone реально льёт поток;
- `receiver_rtp_channel is not None` + `receiver_address` — RTP открыт к колонке X.

**Шаг 1 (малый, безопасный):** публиковать факты в AppState через СУЩЕСТВУЮЩИЙ
`on_state_change` (bridge уже дёргает его при каждом переходе): новые поля
`actual_source_connected`, `actual_source_streaming`, `actual_receiver_addr`.
НЕ трогать route_planner и существующие флаги.

**Шаг 2 (GUI):** в RouteBuilder над софт-кнопками терминальная статус-строка факта:
`ROUTE: IPHONE→FOSI ▶` (труба качает) / `ROUTE: IPHONE→FOSI …` (поднимается) /
`ROUTE: —` (нет маршрута). Расхождение выбора и факта — жёлтым (STATUS_WARN):
видно «выбрал, но не включил». Семантика [LNK] = «привести факт к выбору»
(уже наполовину так после 9318a48).

**Шаг 3 (потом, отдельным решением владельца):** autoresume — персистить желаемый
маршрут + флаг; на старте reconcile-петля приводит факт к желаемому. Тогда
boot-честность (принудительный Play Now после ребута) станет не нужна — GUI
всегда показывает правду, а роутер сам восстанавливает маршрут.

Порядок внедрения: шаг 1 → шаг 2 → прогнать тест-серию §2 заново → только потом шаг 3.

---

## Дополнение 2026-06-11: Codex continuation — Cable/Fosi route tests and guardrails

Контекст: владелец начал новую Codex-сессию от этого runbook. Работа шла по задаче
№1 — серия маршрутных тестов, сначала Fosi как контроль, затем добавление второго
выхода `Maedhawk BT Cable`.

Файлы, изменённые Codex на момент записи:
- `overlay/usr/lib/carthing/a2dp_bridge.py`
- `overlay/usr/lib/carthing/carthing_runtime.py`
- новый append-only лог `docs/route-test-series-results.md`

Важно: изменения горячо задеплоены через `tools/deploy`, но на момент записи НЕ
закоммичены. Git status был:

```text
 M overlay/usr/lib/carthing/a2dp_bridge.py
 M overlay/usr/lib/carthing/carthing_runtime.py
?? docs/route-test-series-results.md
```

### 1. Maedhawk добавлялся, но GUI его не показывал

Живой симптом:
- `[ADD]` находил `Maedhawk BT Cable`, адрес `41:42:9C:A0:BD:14`, `audio=True`.
- Classic bond/link key записывался в `keys.json`.
- A2DP endpoint discovery и `A2DP stream opened+held after pairing` были в логе.
- Но в `state.json` не появлялась speaker-карточка, поэтому GUI не показывал Cable как output.

Диагноз:
- SDP enrichment для Cable вернул UUID вроде `111e`, но не вернул `110b/audio_sink`.
- Enrollment мог потерять уже доказанную роль `speaker`, хотя discovery CoD и pairing flow
  уже доказали `audio=True`.

Правка:
- В `a2dp_bridge.py`, в `pair_speaker()`, если candidate уже audio-output, enrichment
  теперь добавляет `audio_sink` и `110b` к UUID-набору, а не даёт неполному SDP стереть
  speaker-role.

Проверено:
- `py_compile` OK.
- smoke import с `PYTHONPATH=overlay/usr/lib/carthing:overlay/usr/lib/carthing/vendor` OK.
- После деплоя повторный `[ADD]` дал:
  `device card enriched: 41:42:9C:A0:BD:14 -> ['0003', '0100', '1002', '110b', '111e', '1203', 'audio_sink']`.
- `state.json` теперь содержит:
  `speaker Maedhawk BT Cable 41:42:9C:A0:BD:14 ['audio_output', 'control_input', 'transport_control', 'volume_control']`.

### 2. Maedhawk selected, но звук позже уходил в Fosi

Живой симптом владельца:
- Maedhawk выбран как выход, маршрут выглядит активным, но звука нет.
- Через некоторое время звук сам появляется на Fosi.

Лог подтвердил:
- Maedhawk receiver попытки сыпались `L2CAP/CONNECTION_REFUSED_NO_RESOURCES_AVAILABLE [0x4]`.
- В этот период RTP: `sent_to_speaker=False`, dropped рос.
- Потом standby подключал Fosi, открывал его receiver, и RTP менялся на `sent_to_speaker=True`.

Диагноз:
- `handle_classic_connection()` разрешал любой доверенной колонке при входящем classic
  connection вызвать `request_receiver_for_active_source(peer_address)`.
- То есть standby reconnect Fosi мог украсть receiver у выбранного Maedhawk.
- Плюс receiver request entrypoint не уважал `_speaker_backoff`, из-за чего `0x4`
  мог давать частые повторные попытки вместо реальной паузы.

Правка:
- `handle_classic_connection()` теперь открывает receiver для активного source только если
  peer address совпадает с выбранным/default speaker. Иначе пишет:
  `A2DP speaker classic ignored for active route: peer=... selected=...`.
- `ensure_trusted_speakers_connected()` при активном source/transfer не открывает standby
  receiver на невыбранную колонку.
- `request_receiver_connection(..., force=False)` теперь уважает `_speaker_backoff`.
- Явный route selection в `carthing_runtime._apply_route_output()` вызывает
  `request_receiver_connection(key, force=True)`, чтобы ручной `[LNK]` оставался осознанной
  попыткой, даже если был backoff.

Проверено после деплоя:
- `GUI active`
- `AMS: ready`
- `grep -c Traceback` → `0`

Нужно ещё проверить руками:
- Выбрать `Maedhawk BT Cable` → `[LNK]`.
- Если Maedhawk всё ещё даёт `0x4`, звук НЕ должен сам уходить на Fosi.
- Тогда отдельная проблема остаётся именно в Maedhawk AVDTP/resources, а route-steal
  должен быть закрыт.

### 3. Архитектурная договорённость с владельцем

Владелец уточнил ожидаемую модель:
- Play Now — дефолтная и самая безопасная поверхность. После старта и между маршрутами
  система должна стремиться к Play Now/нейтральному состоянию, чтобы не было путаницы и
  самопроизвольного переключения output.
- Возможно, Play Now стоит использовать как промежуточную фазу при смене маршрутов:
  старый route suspend/settle → Play Now/тишина → deliberate activation нового route.
- Каждое устройство должно иметь одну карточку и собственный connector/adapter-state.
  Одна физическая BT-персона может иметь несколько endpoints и попадать одновременно
  в `Inputs` и `Outputs`, но это НЕ должно плодить две независимые device rows.
- Fosi path уже доказан рабочим и должен считаться golden path. При переходе к per-device
  connectors нельзя ломать существующую Fosi-карточку/standby/AVDTP поведение; миграция
  должна быть совместимой и поэтапной.

Текущий код ещё не полностью соответствует этой модели: `a2dp_bridge` всё ещё хранит
один глобальный active receiver (`receiver_protocol`, `receiver_stream`, `receiver_rtp_channel`,
`receiver_address`). Последние правки — guardrails от route-steal, НЕ полная реализация
per-device connector architecture.

### 4. Play Now metadata UI

Владелец заметил, что на Play Now длинные title/artist не помещаются. Решение, которое
сейчас обсуждается:
- НЕ трогать title: оставить крупным как сейчас.
- Сделать бегущей строкой только artist, если он не помещается в одну строку.

Пока НЕ реализовано.

---

## Дополнение 2026-06-11: Codex implemented Play Now artist marquee

Контекст: владелец уточнил UI-решение для длинных метаданных Play Now:
- title НЕ трогать, оставить крупным как сейчас;
- сделать бегущей строкой только artist, если artist не помещается в одну строку.

Изменение:
- `overlay/usr/lib/carthing/screens.py`
- `NowPlayingScreen` получил `_draw_artist_line()`.
- Короткий artist центрируется как раньше.
- Длинный artist рисуется в clipped viewport шириной `T.CONTENT_W` и медленно скроллится.
- Title rendering оставлен прежним: крупный текст, максимум 4 строки с truncate на последней.

Проверка до деплоя:
- `python3 -m py_compile overlay/usr/lib/carthing/screens.py`
- `PYTHONPATH=overlay/usr/lib/carthing CARTHING_UI_THEME=terminal python3 -c "import screens"`
- `PYTHONPATH=overlay/usr/lib/carthing CARTHING_UI_THEME=dark python3 -c "import screens"`
- Сгенерированы dev-preview PNG для terminal/dark с длинным artist; визуально artist
  остаётся одной строкой и не лезет в bottom bar/encoder zone.

Деплой:
- `tools/deploy usr/lib/carthing/screens.py --restart`

Live-проверка после деплоя:
- `GUI active`
- `AMS: ready`
- `grep -c Traceback` → `0`
- В логе сразу появился реальный длинный artist:
  `Murray Perahia, Wolfgang Amadeus Mozart, English Chamber Orchestra`, что подходит
  для live-проверки на устройстве.

---

## Дополнение 2026-06-11: Codex follow-up — global receiver guardrail tightened

После первого route-steal guardrail владелец попросил вернуться к устройствам. Повторный
лог показал, что Fosi всё ещё мог стать фактическим receiver не через active-source branch,
а раньше: standby открывал AVDTP к Fosi до того, как `source_stream_active=True`. Когда
iPhone начинал лить RTP, уже открытый Fosi receiver принимал поток.

Дополнительная правка:
- `overlay/usr/lib/carthing/a2dp_bridge.py`
- `ensure_trusted_speakers_connected()` теперь вычисляет `receiver_target =
  default_speaker_address()` и открывает AVDTP standby receiver только для этого адреса.
- Остальные trusted speakers не получают media receiver standby, пока `a2dp_bridge`
  имеет один глобальный `receiver_protocol/receiver_stream/receiver_rtp_channel`.

Смысл:
- Это НЕ финальная per-device connector architecture.
- Это guardrail для текущей single-receiver реализации: невыбранная Fosi больше не должна
  занимать единственный receiver-slot, когда default/selected output — Maedhawk.
- Fosi остаётся trusted и golden path, но не должен становиться фактическим output без
  явного выбора/default.

Проверка:
- `python3 -m py_compile overlay/usr/lib/carthing/a2dp_bridge.py`
- `PYTHONPATH=overlay/usr/lib/carthing:overlay/usr/lib/carthing/vendor python3 -c "import a2dp_bridge"`
- `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`
- после рестарта: `GUI active`, `AMS: ready`, `Traceback=0`
- `state.json`: Maedhawk default speaker, Fosi trusted but not default.
- 30-секундный live-tail после рестарта не показал новых Fosi standby/receiver событий.

Следующая ручная проверка:
- Play Now → выбрать `Maedhawk BT Cable` → `[LNK]` → включить iPhone audio.
- Если Maedhawk снова даёт `0x4`/тишину, Fosi НЕ должен сам стать `sent_to_speaker=True`.

### Correction: этот guardrail отменён

Владелец сразу поймал регрессию: запрет non-default AVDTP standby ломает Fosi.
Fosi требует held AVDTP standby, иначе уходит обратно в pairing/discoverable состояние.

Что сделано после замечания владельца:
- Из `ensure_trusted_speakers_connected()` удалён фильтр `address != default_speaker_address()`.
- `a2dp_bridge.py` снова задеплоен через `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`.
- После рестарта:
  - `GUI active`
  - `AMS: ready`
  - `Traceback=0`
  - Fosi снова поднял receiver:
    `A2DP receiver sink selected: address=C4:A9:B8:70:2F:E5 codec=AAC seid=3`
    и `A2DP_SPEAKER_STREAM_STARTED codec=AAC seid=3`.

Текущая позиция:
- Fosi golden path восстановлен.
- Нельзя решать route-steal простым отключением standby для невыбранных колонок.
- Оставшиеся guardrails допустимы: backoff на receiver retry и запрет active-source
  classic connection от невыбранного speaker вызывать receiver.
- Настоящее решение — per-device connector state или аккуратная transition-state между
  Play Now и выбранным output, но без потери Fosi standby-инварианта.

---

## Дополнение 2026-06-11: Codex implementation — per-speaker connector state

Владелец сформулировал правильную архитектурную границу: мы не знаем, какое следующее
Bluetooth-устройство появится и какие standby/AVDTP/AVRCP условия оно потребует.
Ручные исключения под Fosi или Maedhawk не масштабируются. Нужен слой, где каждое
trusted output-устройство получает собственное состояние коннектора.

Что реализовано:
- `overlay/usr/lib/carthing/a2dp_bridge.py`
- Добавлен `SpeakerConnector` и карта `_speaker_connectors[address]`.
- Старые поля `receiver_connection/receiver_protocol/receiver_stream/receiver_rtp_channel/...`
  оставлены как compatibility view текущего выбранного коннектора, чтобы не ломать
  остальной runtime одним большим рефактором.
- `setup_receiver()` теперь пишет AVDTP protocol/source/stream/rtp_channel/error в connector
  конкретного speaker address.
- `_close_receiver_protocol()`, `on_receiver_disconnected()`, `stop_receiver_stream()`,
  `receiver_loop()`, `request_receiver_connection()` и retry path переведены на connector-aware
  поведение.
- `forward_packet()` больше не отправляет RTP в "последний открытый receiver". Он берёт
  `default_speaker_address()` и шлёт только в `rtp_channel` выбранного speaker connector.
  Это ключевой guardrail против Fosi route-steal при выбранном Maedhawk.
- `setup_receiver()` заменил `set_connected_speaker()` на `set_speaker_connected(address, True)`.
  Это важно для новой модели: несколько standby output-коннекторов могут быть живы одновременно;
  выбор маршрута не должен стирать connected state других устройств.

Что намеренно НЕ сделано этим шагом:
- Не введены параллельные connect task per speaker. Пока `_connect_task` остаётся глобальным
  сериализатором HCI/AVDTP операций.
- Не переписан весь registry/GUI contract; device cards остаются на существующей модели.
- Не удалён Fosi held standby. Напротив, per-device connector state нужен именно потому, что
  Fosi требует standby, а Maedhawk должен иметь независимый connector.

Проверка до деплоя:
- `python3 -m py_compile overlay/usr/lib/carthing/a2dp_bridge.py`
- `PYTHONPATH=overlay/usr/lib/carthing:overlay/usr/lib/carthing/vendor python3 -c "import a2dp_bridge; print('import ok')"`

Деплой:
- `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`
- После первой проверки добавлена correction: `set_connected_speaker()` заменён на
  `set_speaker_connected(address, True)`, затем выполнен второй deploy того же файла.

Live-проверка после второго деплоя:
- `GUI active`
- `AMS: ready`
- `Traceback=0`
- Свежий log window после `2026-06-11 20:27:03`:
  - `A2DP_SPEAKER_STREAM_STARTED codec=AAC seid=3` для Fosi (`C4:A9:B8:70:2F:E5`)
  - `A2DP_SPEAKER_STREAM_STARTED codec=SBC seid=1` для Maedhawk (`41:42:9C:A0:BD:14`)
  - нет новых `A2DP receiver disconnected`
  - нет новых `A2DP receiver connect failed`

Следующая ручная проверка:
- В GUI выбрать `Maedhawk BT Cable` как output, включить iPhone audio.
- Ожидаемое поведение после этой реализации: если Maedhawk способен принять RTP, звук идёт
  на Maedhawk; если Maedhawk молчит/ломается, Fosi не должен становиться фактическим
  `sent_to_speaker=True` только потому, что его standby connector жив.
- Если звук на Maedhawk всё ещё не слышен, следующий слой диагностики — сам Maedhawk
  receiver path: codec SBC, endpoint seid=1, AVRCP volume=120, возможная mute/line-output/
  analog-side проблема или AVDTP stream state, а не route stealing.

### Hotfix after live route test: RTP callback must not raise

Live test immediately after per-speaker connector deployment:
- Owner started music and switched route to Maedhawk.
- GUI appeared frozen and no audio was heard.

Evidence:
- Log flooded with thousands of Tracebacks from Bumble packet path.
- Root exception:
  `bumble.core.InvalidStateError: channel not open`
- Stack pointed to `a2dp_bridge.py forward_packet()` calling `channel.send_pdu(payload)`.
- This happened after Maedhawk initially accepted RTP:
  `A2DP_BRIDGE_RTP forwarded=1..9 sent_to_speaker=True`, then its RTP channel closed.

Fix applied:
- `forward_packet()` now wraps `channel.send_pdu(payload)` in `try/except`.
- On send failure it:
  - does not let the exception escape Bumble's packet callback;
  - clears selected connector `source/stream/rtp_channel`;
  - clears legacy `receiver_source/receiver_stream/receiver_rtp_channel` if it is the selected route;
  - increments dropped packet count;
  - logs one `A2DP RTP send dropped: speaker=... error=...`;
  - schedules receiver retry, which now forces a full stream rebuild instead of resuming a dead media channel.

Verification after final hotfix deploy:
- `python3 -m py_compile overlay/usr/lib/carthing/a2dp_bridge.py`
- `PYTHONPATH=overlay/usr/lib/carthing:overlay/usr/lib/carthing/vendor python3 -c "import a2dp_bridge; print('import ok')"`
- `tools/deploy usr/lib/carthing/a2dp_bridge.py --restart`
- Fresh window after `2026-06-11 20:36:00`:
  - `GUI active`
  - `AMS: ready`
  - Fosi: `A2DP_SPEAKER_STREAM_STARTED codec=AAC seid=3`
  - Maedhawk: `A2DP_SPEAKER_STREAM_STARTED codec=SBC seid=1`
  - no fresh `Traceback`
  - no fresh `Exception in on_packet`

Current interpretation:
- GUI freeze was not a renderer bug. It was log/event-loop starvation from unhandled RTP send
  exceptions in the Bumble packet callback.
- Maedhawk can accept an AVDTP stream and initially receives RTP, but its media channel closed
  shortly after playback. The next diagnostic target is why Maedhawk closes its RTP channel or
  why its analog side remains silent, not Fosi stealing the route.

### Codec compatibility finding: AAC source into SBC-only Maedhawk

Owner clarified after the hotfix:
- Maedhawk is selected and iPhone sees Car Thing as the audio output.
- iPhone keeps sending music, but no sound is heard on Maedhawk.

Log evidence:
- iPhone repeatedly configured Car Thing input as AAC:
  `A2DP_SOURCE_SET_CONFIGURATION codec=AAC`
- Maedhawk receiver is SBC-only in this run:
  `A2DP receiver sink selected: address=41:42:9C:A0:BD:14 codec=SBC seid=1`
- The bridge forwards encoded RTP; it does not transcode AAC to SBC.

Conclusion:
- This is a codec mismatch, not a route-selection bug.
- Fosi works with AAC because its receiver accepts AAC.
- Maedhawk accepts only SBC, so AAC RTP delivered into the Maedhawk SBC stream produces
  silence and/or closes the media channel.

Fix applied:
- `a2dp_bridge.py` now tracks `source_codec_name`.
- Source endpoint advertisement is route-aware:
  - if selected receiver codec is SBC, Car Thing offers iPhone `SBC-only route-compatible`;
  - otherwise it can still offer `AAC+SBC`.
- `forward_packet()` now drops codec-mismatched RTP instead of sending it into the wrong
  decoder, and schedules source renegotiation.
- `carthing_runtime._apply_route_output()` now calls
  `bridge.ensure_source_codec_matches_route()` after selecting/preparing a speaker route.

Verification:
- Local `py_compile` and import passed.
- Deployed `a2dp_bridge.py` and `carthing_runtime.py` with restart.
- Fresh window after `2026-06-11 20:41:00`:
  - `GUI active`
  - `AMS: ready`
  - Fosi receiver: AAC
  - Maedhawk receiver: SBC
  - no fresh `Traceback`

Next manual test:
- Select Maedhawk.
- Re-select Car Thing as iPhone audio output if iOS stays on the old AAC source session.
- Expected log for Maedhawk success path:
  - `A2DP source endpoint profile=SBC-only route-compatible`
  - `A2DP_SOURCE_SET_CONFIGURATION codec=SBC`
  - `A2DP_SOURCE_START codec=SBC`
  - `A2DP_BRIDGE_RTP ... sent_to_speaker=True`

### Correction after owner report: GUI output and bridge default diverged

Owner reported:
- Fosi stopped behaving as an output.
- Selecting Fosi in GUI still resulted in Maedhawk being used.

Evidence:
- `state.json` showed:
  - Fosi: `route_output=True`
  - Maedhawk: `default=True`
- `forward_packet()` and source codec negotiation use `bridge.state.default_speaker_address()`.
- Runtime route selection updated `gui.app_state.select_default_speaker(key)`, but did not update
  `transfer.bridge.state.select_default_speaker(key)`.
- `_on_route_output_select()` also saved trusted state before `_apply_route_output()` changed
  the default speaker, so default speaker changes were not persisted reliably.

Fix applied:
- `carthing_runtime._apply_route_output()` now updates both:
  - `gui.app_state.select_default_speaker(key)`
  - `transfer.bridge.state.select_default_speaker(key)`
- It then calls `gui.app_state.save_trusted()` after the default speaker mutation.

Verification:
- `python3 -m py_compile overlay/usr/lib/carthing/carthing_runtime.py`
- `PYTHONPATH=overlay/usr/lib/carthing:overlay/usr/lib/carthing/vendor python3 -c "import carthing_runtime; print('import ok')"`
- Deployed `usr/lib/carthing/carthing_runtime.py --restart`.

Important:
- This was the cause of "Fosi selected but Maedhawk still used".
- After this fix, selecting Fosi again should update the transport default, not only the GUI row.

Hardware note from this turn:
- Car Thing has live ALSA card `AML-AUGESOUND`.
- PCM `00-00` is `TDM-A-T9015-audio-hifi-alsaPORT-i2s ... playback 1 : capture 1`.
- The current Bluetooth-to-Bluetooth relay path does not use T9015/ALSA; it forwards encoded RTP
  between A2DP sessions. T9015 would matter for local Play Now / analog playback / a future
  decode-transcode-mix pipeline.

---

## Дополнение 2026-06-12: аудио-заикание — диагноз, фиксы, остаток

**Доказанный механизм** (зонды max_gap_ms + render-таймер, корреляция в логе):
кадр GUI держал event-loop 77–92 мс × 4-5/с → дыры 130–180 мс во входе RTP →
буфер Fosi (150 мс) опустошался → заикание. Прямая пара iPhone↔колонка чистая,
потому что там нет нашего цикла.

**Сделано** (`480ea0f`, `d6aad82`, `492af14`, page-сериализация в `_on_route_activate`):
- периодический рендер → executor-поток (коалесинг кадров);
- GC freeze + пороги (паузы gen2 по PIL-куче);
- кадры ≤2/с пока течёт стрим (GIL-укусы реже);
- standby не пейджит посторонних при активном стриме; receiver_loop чтит бэкофф;
- [LNK]: только выбранная колонка + ожидание её коннекта перед connect_source
  (page-коллизия давала HCI 0x12 «маршрут не переключается»).

**Остаток/идеи дожать до идеала:**
- GIL: стоковый CPython 3.14 (GIL=True). Радикально: GUI в ОТДЕЛЬНЫЙ ПРОЦЕСС
  (compositor-process, состояние через сокет/shared) — рендер вообще не трогает
  интерпретатор BT. Или free-threaded 3.14t в buildroot (проверить пакет).
- `/dev/audiodsp0` (CONFIG_AMLOGIC_AUDIO_DSP, major 257) — аппаратный DSP:
  ресёрч ioctl (kernel 4.9 amlogic, driver audio_dsp); кандидат на транскод
  AAC→SBC для SBC-only приёмников (Maedhawk) вместо CPU.
- Роли piconet (Gemini-ресёрч 2026-06-11): стать master обоих линков
  (HCI_Switch_Role), sniff off при стриме, 3-DH5; delay reporting суммарной
  задержки. Файлы ресёрча: /tmp/gemini*-bt-research.txt (скопировать в docs!).
- Зонды (max_gap_ms в RTP-строке, render slow) оставлены — дешёвые, полезные.

---

## ЗАДАНИЕ CODEX — ночь 2026-06-12 (Claude уходит по лимиту)

Прочитай ВЕСЬ этот файл и `docs/route-test-series-results.md` (протокол append-only,
пиши туда же). Железные правила §1 действуют БУКВАЛЬНО — особенно: tools/deploy,
smoke-ИМПОРТ после правок (py_compile НЕ ловит NameError), INVARIANTS.md перед BT-правками,
чек-лист §4 после каждого деплоя. Звук сейчас РАБОТАЕТ (владелец подтвердил) — не сломай.

### Контекст: что уже сделано по заиканию (вечер 2026-06-11, Claude)
Хронология фиксов: `492af14` (бэкофф+радио-гвард пейджинга) → page-сериализация [LNK]
(`carthing_runtime`) → `480ea0f` (рендер в executor-поток; ДОКАЗАНО зондами: кадр держал
loop 77-92 мс → дыры 130-180 мс) → `d6aad82` (GC freeze + кадры ≤2/с при стриме) →
`ade2095` (radio tune: BLE 45-60ms/latency 4 при стриме, master на линке колонки).
Результат: max_gap 80-130 мс (буфер Fosi 150), на слух чисто. Зонды живут в логе:
`A2DP_BRIDGE_RTP ... max_gap_ms=` и `render slow (thread)`.

### Задача A (первая): проверить radio tune под музыкой
1. Маршрут iPhone→Fosi, музыка ≥3 мин. В логе ищи `RADIO_TUNE:` строки:
   - `BLE ... 45-60ms latency=4 (stream)` при старте, `15-30ms latency=0 (idle)` на паузе;
   - `speaker link role=...`. iOS может отклонить параметры — это лог, не бага.
2. Собери max_gap_ms по ≥30 окнам ДО/ПОСЛЕ (до = коридор 80-132). Если стало хуже
   или AMS/ANCS развалились — `CARTHING_RADIO_TUNE=0` в /etc/default/carthing (через
   remount rw! см. tools/deploy исходник) и зафиксируй в протоколе.
3. Результаты → docs/route-test-series-results.md.

### Задача B: ресёрч /dev/audiodsp0 (НЕ кодить в runtime!)
Узел: major 257, CONFIG_AMLOGIC_AUDIO_DSP, ядро 4.9 amlogic. Цель ресёрча: можно ли
кормить DSP AAC и забирать PCM (или сразу SBC) для транскода AAC→SBC (Maedhawk-кейс).
Шаги: найти драйвер в исходниках ядра (buildroot dl/ или github amlogic 4.9,
drivers/amlogic/audiodsp*), выписать ioctl-набор и формат обмена; проверить наличие
firmware DSP в /lib/firmware на устройстве; НАПИСАТЬ standalone-тест в tools/
(не трогая runtime). Итог: docs/audiodsp-research.md — интерфейс + вердикт «годен/нет».

### Задача C: дизайн GUI-процесса (ресёрч + план, БЕЗ реализации этой ночью)
Остаточные GIL-укусы лечатся только выносом GUI в отдельный ПРОЦЕСС. Ловушка:
AppState — ОБЩЕЕ мутируемое состояние BT-логики и GUI (a2dp_bridge.state ЕСТЬ
app_state), наивный сплит невозможен. Связка с carthing-release-architecture:
docs/l8-state-model.md — там модель состояния, бери её за основу.
Жду от тебя: docs/gui-process-design.md с (1) границей процессов (рекомендую:
GUI-процесс владеет input+compositor+DRM, runtime шлёт снапшоты состояния,
GUI шлёт интенты обратно — unix socket, msgpack/json); (2) протоколом снапшота
(какие поля AppState читают экраны — выпиши grep'ом); (3) планом миграции
ПОЭТАПНО с работающей системой на каждом шаге; (4) рисками (regions/hit-test,
шторка, анимации). НЕ реализуй, пока владелец не утвердит дизайн.

### Задача D (если останется ресурс): мелочи из §3
- №3 авто-ретрай connect_source (PAGE_TIMEOUT спящего iPhone) — паттерн 3/8/15 c.
- Maedhawk: сверить нашу SBC-конфигурацию с его GetCapabilities (битпул!) —
  его перезагрузки при воспроизведении похожи на превышение возможностей.
- ПРОВЕРЬ освобождение порта: бывает, после kill старый runtime держит HCI.

### НЕ ДЕЛАТЬ этой ночью
- BAKE (блок прошивки) — только при владельце.
- Реализацию GUI-процесса и DSP-интеграцию — только дизайн/ресёрч.
- Никаких правок vendored bumble без check-bumble-vendor.py.
- Push в git.

### Задача B+ (приоритет ПОДНЯТ владельцем): T9015 DAC — есть ли у Car Thing голос
Владелец прав концептуально: ALSA-карта AML-AUGESOUND имеет PLAYBACK-устройство
pcmC0D0p, T9015 (встроенный ЦАП SoC) вкомпилен (CONFIG_AMLOGIC_SND_CODEC_AMLT9015).
Если аналог разведён на плате — Car Thing сам становится аудиовыходом: iPhone→BT→
CarThing→T9015→ПРОВОД→Fosi line-in. Тогда в эфире остаётся ОДИН BT-линк и все
проблемы двух classic исчезают классом. Шаги:
1. Куда выведен DAC: /proc/device-tree (sound-ноды, pinmux), схемы/teardown Superbird
   (искать line-out/test pads; в carthing-hardware-map памяти агента есть карта I2C/DT).
2. Проиграть тон: на устройстве НЕТ aplay/tinyplay/libasound. Варианты: (а) минимальный
   ALSA-плеер на python через ioctl SNDRV_PCM_* (ядро 4.9, ~100 строк, констант полно
   в исходниках ядра); (б) собрать СТАТИЧЕСКИЙ tinyplay aarch64 вне общего build-тома.
   Тон 440Гц уже лежит: /tmp/tone.raw (s16le stereo 48k, 3с).
3. Владелец слушает устройство (и щупает осциллографом пятаки, если скажет где).
4. Вердикт в docs/audiodsp-research.md: «голос есть/нет, куда выведен».
ВНИМАНИЕ: amaudio/amaudio_ctl — легаси-узлы, audio_data_debug существует; не путать
с audiodsp0 (декодер) из задачи B. Это РАЗНЫЕ части тракта: DSP=декод, T9015=ЦАП.

### Задача B+ — УТОЧНЕНИЕ (владелец напомнил: T9015 ДОКАЗАН 2026-05-24)
НЕ переоткрывать! Источники истины:
- `carthing-release-architecture/docs/hardware-capability-inventory.md` §«Audio Output —
  T9015 Playback» — ПОЛНЫЙ рецепт: ALSA ioctl-цепочка PVERSION→HW_REFINE(S16_LE/48k/stereo,
  cmask=0x0007f300)→HW_PARAMS(rate 48000/1, msbits=16)→write(). Синус 440Гц уже принимался.
- `carthing-device-backups/artifacts/T9015-PLAYBACK-DTS-PATCHES.md` — DTS-патчи
  (0001-amlogic-tdm-unmute-playback + acodec/clkc_audio/arb ноды).
- ПРОВЕРЕНО Claude 2026-06-12 НА ЖИВОМ buildroot-ядре: dmesg несёт ту же сигнатуру
  «T9015 acodec used by auge, tdmout:0» + «aml_tdm_platform_probe tdm ID=0 lane_cnt=4»
  → текущий bake УЖЕ содержит рабочий тракт, патчить ядро НЕ надо.
- Тон готов: /tmp/tone.raw (s16le/48k/stereo, 3с). Дело за: восстановить ioctl-плеер
  по рецепту (структуру snd_pcm_hw_params собирать аккуратно, ядро 4.9), сыграть,
  владелец слушает/щупает. Куда физически выведен tdmout:0 — по DTS-патчу видно
  пины; вопрос line-out-пятаков на плате остаётся открытым.
- Стоковая архитектура подтверждена тем же документом: у Spotify аудиовыхода НЕ
  было, T9015 в шипнутом продукте не использовался — мы строим новую способность.

### «РАБОТА НАД ЧИПОМ» — этажи построены Claude 2026-06-12 (продолжай отсюда)
Решение владельца: фундамент кладёт Claude, Codex продолжает по комментариям.
- **Этаж 1 ГОТОВ** `audio_out_t9015.py` (6476671): движок ЦАП на голых ALSA ioctl
  (структуры 4.9 задокументированы построчно), XRUN-recovery, CLI tone/raw.
  ПРОВЕРЕНО на железе: HW_PARAMS 48000/1 msbits=16, синус играется в реальном темпе.
- **Этаж 2 ГОТОВ** `audio_local_sink.py` (632b11f): очередь + поток-плеер +
  ГНЕЗДО декодера (AudioDecoder). Селфтест на железе 150/150 кадров.
  Карта интеграции — в докстринге модуля. ЧИТАТЬ ЕГО ПЕРВЫМ.
- **Этаж 3 — ТВОЙ (декодер)**: реализуй AudioDecoder поверх /dev/audiodsp0
  (задача B: ioctl-ресёрч драйвера) — вход AAC payload из RTP, выход PCM S16LE/48k.
  Если DSP не взлетит — программный SBC-декодер (SBC прост; AAC в софте НЕ пытаться).
- **Этаж 4 — врезка (ОДНА строка)**: a2dp_bridge.forward_packet -> local_sink.feed_rtp
  когда активный выход = LOCAL_SINK_KEY. НЕ раньше работающего декодера.
- **Этаж 5 — честный endpoint**: «Car Thing line-out» в route_outputs ТОЛЬКО после
  того, как этаж 3-4 реально звучат (правило boot-честности: мёртвых выходов в GUI нет).
- Физический выход: владелец подтвердил — динамиков на плате нет; куда выведен
  tdmout:0 — выяснить по DTS (line-out пятаки для провода к Fosi line-in).

### «РАБОТА НАД ЧИПОМ» — ФИНАЛ СМЕНЫ CLAUDE (65a82f8): осталась ТОЛЬКО задача-декодер
Архитектура пересажена ЦЕЛИКОМ и проверена на железе (e2e 150/150 кадров):
- этаж 1: audio_out_t9015.py — ЦАП-движок (ioctl, XRUN-recovery);
- этаж 2: AudioLocalSink — очередь+поток+гнездо AudioDecoder;
- этаж 2.5: sink = ОТДЕЛЬНЫЙ ПРОЦЕСС (audio_local_sink.py serve, SOCK_SEQPACKET
  /run/carthing/local-sink.sock, кадр = codec_id+payload; коннект=DAC open);
- этаж 4: врезка в a2dp_bridge.forward_packet (флаг local_sink_enabled) +
  local_sink_client.py (неблокирующий, drop-on-EAGAIN, ленивый спавн демона);
- этаж 5: endpoint «Line out / T9015 DAC» в route_outputs за CARTHING_LINEOUT_ENABLE=1.

**ТВОЙ ХОД, CODEX — этаж 3, декодер** (всё остальное НЕ трогать):
1. Ресёрч audiodsp0 (задача B выше) → класс в НОВОМ файле audiodsp_decoder.py,
   контракт AudioDecoder.decode("aac", payload)->PCM S16LE/48k/stereo.
2. Подключение ровно в ОДНОМ месте: audio_local_sink._serve(), выбор декодера
   (комментарий-якорь там стоит). PassthroughPcmDecoder не удалять (тесты).
3. Проверка БЕЗ BT: tools-скриптом скормить демону AAC-кадры из дампа
   (записать дамп: лог payload из forward_packet при играющем маршруте).
4. Когда зазвучит: CARTHING_LINEOUT_ENABLE=1 в /etc/default/carthing → выход
   появится в Routes; [LNK] на него уже работает (ветка в _apply_route_output).
5. RTP-шапка: payload в sink приходит КАК ЕСТЬ из RTP (для AAC это LATM/RTP
   обвязка!) — в декодере сначала снять RTP/media-обвязку (см. как
   bumble.codecs.AacAudioRtpPacket разбирает; vendored bumble уже есть).

### Последние штрихи Claude (5d723da) — задача №3 закрыта
- connect_source: авто-ретрай 3/8 c на PAGE_TIMEOUT (спящий iPhone) — [LNK]
  больше не требует второго тапа. Другие ошибки НЕ маскируются.
- Дампер для этажа 3: CARTHING_SINK_DUMP=<file> у sink-демона пишет
  [codec_id][u32 len][payload] — сними дамп с живого маршрута line-out один раз
  и разрабатывай декодер офлайн.

---

## 2026-06-12 ДНЁМ — LINE-OUT ЖИВ END-TO-END (Claude, сессия после сброса лимитов)

**Полная цепь работает с живым iPhone владельца** (коммиты `7ecb270`, `73ad409`):
iPhone -> BT A2DP (SBC 44100 joint-stereo, негоциация SBC-only) -> forward_packet ->
unix socket -> sink-процесс -> SBC-декодер (C-ускоритель, бит-в-бит с ffmpeg,
x1.7 rt) -> T9015 DAC: ALSA state RUNNING, hw_ptr бежит, 0 ошибок декода.

Ключевые открытия для продолжателей:
- bumble rtp_packet = ВЕСЬ RTP-пакет (12Б шапка + 1Б media header) — декодер
  ищет 0x9C с CRC-валидацией кандидата и кэширует смещение.
- Кросс-сборка C на Mac: clang -target aarch64-unknown-linux-gnu -nostdlib
  -shared — freestanding .so грузится glibc-устройством без sysroot.
- Эталонная проверка декодера: tools/test_sbc_decoder.py (ffmpeg = референс).
- CARTHING_LINEOUT_ENABLE=1 уже в /etc/default/carthing.

**Следующее по line-out:**
1. ФИЗИКА: найти выход T9015 на плате (DTS tdmout:0 -> пины), припаять провод
   к Fosi line-in — и слушать. (Владелец: динамиков на плате нет.)
2. Долгая обкатка: XRUN-счётчик (audio_out_t9015.xruns), дрейф часов
   iPhone vs TDM-клок (буфер очереди сгладит, но мониторить).
3. AAC-этаж (DSP, задача B) — для качества выше SBC.
4. Codex'ова тест-серия §2 — теперь с третьим выходом Line out в матрице.
