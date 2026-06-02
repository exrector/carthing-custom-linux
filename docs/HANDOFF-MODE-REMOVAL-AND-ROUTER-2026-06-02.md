# HANDOFF — удаление режимов + сервис-роутер (2026-06-02, Claude)

Цель документа: любой агент/человек может подхватить и продолжить. Здесь — НАМЕРЕНИЕ,
текущее состояние, что сделано, что осталось, и операционные грабли. Ветка: `release-integration`.

## 0. Источник истины по идее
Полный посыл проекта (читать первым): память владельца
`~/.claude/projects/-Users-exrector/memory/carthing-vision-and-essence.md`.
4-месячный исторический референс: `docs/context-recovery-tests-protocols-2026-06-02.md`.
Деталь BLE/CTKD/деплой: `~/.claude/.../memory/carthing-unified-runtime.md`.

## 1. НАМЕРЕНИЕ (решение владельца, 2026-06-02)
Car Thing = **сервис-ориентированный роутер/аудиоинтерфейс**, НЕ «пульт с режимами».
- ОС делит мир на **СЕРВИСЫ (endpoints: direction × protocols × capabilities)**, не на устройства.
  Одно устройство = мешок эндпоинтов; Mac живёт и в Inputs, и в Outputs одновременно.
- **РЕЖИМЫ (remote/transfer/router/mac/quiet/service) УДАЛЯЮТСЯ ФИЗИЧЕСКИ.** Никакого глобального
  mode/session, меняющего поведение коннектов. Истина = ГРАФ МАРШРУТОВ (активные рёбра input→output).
  Владелец: «Codex ушёл не туда, мне неважно что он сделал, режимы вырезать прямо в release-integration».
- **Подключения по направлению инициатора:**
  - iPhone инициирует ТОЛЬКО BLE (Apple: аксессуар = peripheral). BLE-линк постоянный.
  - CTKD: одна BLE-пара даёт LE LTK/IRK + BR/EDR classic link-key в keystore (флаг
    `SMP_LINK_KEY_DISTRIBUTION_FLAG` в `accessory_orchestrator.pairing_config_factory`).
  - Classic к iPhone инициирует САМ Car Thing (исходящий page, `a2dp_bridge.connect_source`),
    рвёт его сам (`disconnect_source`). «Назад на BLE» = закрыть classic; BLE не падал.
  - Classic discoverable=False ВСЕГДА. Колонки (Fosi) ищем инквайром (исходящий), не рекламируемся.
- online/offline = СТАТУС, не триггер автозвонка. Доверенные держатся в standby (LinkManager).

## 2. ФУНДАМЕНТ — НЕ ТРОГАТЬ (это хорошее, на нём строим)
`TrustedDeviceRegistry` (один реестр) · `route_graph.py` (Capability/Endpoint/Protocol/TrustedDevice/
PlannedSession/Route) · `RoutePlanner` (конфликты full-duplex/эксклюзив) · `LinkManager`
(`connect_idle`=standby, `probe`=online) · адаптеры BLE/AMS/ANCS/CTS/HID, `a2dp_bridge`,
`accessory_orchestrator` (CTKD + видимость), `safe_link_key_provider` (тихий classic по сохранённому
link-key). NB: внутреннее имя `PlannedSession` = «спланированный МАРШРУТ», это НЕ режим — оставить.

## 3. СДЕЛАНО в этой сессии (коммиты release-integration, снизу вверх)
- `bee76e7` CTKD включён (link-key флаг) + classic discoverable=False (канон 0d0ffa7) + перестали
  ломиться в неспаренный Fosi в standby + убит лог-флуд «no trusted speaker» (per-packet retry).
- `70603dc` `a2dp_bridge.connect_source` + вызов из transfer.activate(): Car Thing САМ звонит
  classic'ом bonded-айфону (исходящий).
- `f9e9b1f` `disconnect_source` + хранение classic-ACL источника: Car Thing рвёт classic сам
  (полный цикл classic↔BLE у Car Thing). + хранит входящий classic от доверенного источника.
- `7769a73` GUI «Добавить устройство»: тапабельный список = ТОЛЬКО audio-динамики (исходящий канал)
  + стабильный порядок по адресу → убрало баг «не динамик» (тап попадал в iPhone из-за пересортировки).
  + `C.truncate` → текст не вылезает за окно.
- `e8bc5b3` STAGE 1 удаления режимов: boot НЕ применяет режим; выбор входа/выхода → `_activate_route()`
  (план через RoutePlanner + старт коннекторов только при наличии ребра). `_on_session_select`→noop.
  Загрузка чистая на QN19.

## 4. ОСТАЛОСЬ — STAGE 2: физически удалить мёртвый mode-код
Сейчас осиротевший mode-диспетчер ещё лежит (boot его не зовёт, но код есть). Удалить:
Файлы ещё ссылающиеся на режимы (`grep active_session|_apply_session|session_select|mode_select|
session_presets|VALID_SESSIONS|build_preset_session|show_session_screen|SessionScreen|MODES`):
`carthing_runtime.py · app_state.py · gui_controller.py · intents.py · power_policy.py ·
session_presets.py · settings_service.py · screens.py · runtime_model.py · ui_screen.py`.
Конкретно:
- `carthing_runtime.py`: удалить `_apply_session`, `_build_session_plan`, `VALID_SESSIONS`,
  `from session_presets import ...`. (Уже не вызываются.)
- `session_presets.py`: удалить файл целиком.
- `app_state.py`: убрать `active_session`/`_active_session`/`_normalize_session`/`MODES`/`SESSIONS`,
  `transfer_active`-как-режим (transfer_active гейтить по активному маршруту, не глобально).
- `runtime_model.py`: убрать `active_session`/`mode_status`.
- `power_policy.py`: убрать `set_active_session`.
- `settings_service.py`: перестать персистить `active_session`.
- `screens.py`: удалить экран Сессий/Режимов (`SessionScreen`/`ModesScreen`) + пункт меню «Сессии».
- `intents.py` / `gui_controller.py`: удалить интенты `session_select`/`mode_select` + их разводку,
  alias `MODES = SESSIONS`.
- ВАЖНО после каждого файла: py_compile + деплой + рестарт + проверка чистой загрузки (модель
  «удаляй по чуть-чуть, не брикай boot»).

ОТКРЫТЫЙ ВОПРОС ВЛАДЕЛЬЦУ (до удаления UI): экран «Сессии» убрать совсем, а его место занимает
маршрутный экран **ВХОД|ВЫХОД** (две колонки-вью над реестром; один девайс может быть в обеих;
активация маршрута — явным действием/long-press, обычный тап только выбирает)? Или пока просто
снять пункт «Сессии», маршрут оставить где есть? Ответ не получен — спросить перед резом UI.

## 5. ИЗВЕСТНЫЕ БАГИ
- ИСПРАВЛЕНО: «не динамик» (пересортировка списка), текст за окном, CTKD-флаг, force-dial Fosi, флуд.
- ОСТАЁТСЯ: **Fosi бондится (link-key в keystore) и ACL поднимается, но A2DP-медиапоток (AVDTP) к
  колонке не открывается → Fosi мигает «жду», юзер читает как «не подключено».** Нужно: открывать
  AVDTP к динамику при активации маршрута/добавлении, чтобы колонка вставала «подключено».
  Лог-доказательство пары: `A2DP classic link-key found` + `A2DP_SPEAKER_STANDBY_CONNECTED`.
- ОСТАЁТСЯ (бэклог из истории): S50 self-heal/conductor (рантайм стартует до готовности hci0 →
  иногда `HCI busy`); refresh sticky-реконнекта после новой пары без ребута; route-planner конфликты.

## 6. ПРОДУКТ/UX (направление, не код)
Enrollment делить по СПОСОБУ КОНТАКТА, не по типу устройства: входящий (открыл меню = ты видим,
выбери на телефоне), исходящий (тапни динамик в скане), проводной (USB — сам появился). После любого
подключения — глубокое профилирование (`EnrollmentManager`) → один реестровый объект со всеми
эндпоинтами → сам появляется в нужных вью. QR для iPhone отклонён (iOS не BT-парится по QR без
app/AccessorySetupKit). Держать планку «готовый красивый современный продукт».

## 7. ОПЕРАЦИОНКА (устройство QN19)
- SSH: `root@172.16.42.77` (если VPN ломает маршрут: `sudo route add -host 172.16.42.77 -interface en14`).
  efuse `8555R08SQN19`, BD `30:E3:D6:00:5F:A4`. Имя в логе «Car Thing» (efuse-имя `Car Thing (SN: QN19)`
  — проверить, почему без SN: alias CARTHING_BT_ALIAS или efuse-read; чек-лист п.2 истории).
- Hot-deploy (НЕ scp, COPYFILE_DISABLE):
  `printf '%s\n' <files> | COPYFILE_DISABLE=1 tar --no-xattrs -cf - -T - | ssh root@IP 'mount -o remount,rw /; tar -xf - -C /'`
- Рестарт (S50 НЕ всегда self-heal'ит после kill!):
  `kill <runtime_pid>; rm -f /run/carthing/media-remote-supervisor.pid; setsid sh /etc/init.d/S50-carthing-remote`
- Лог рантайма (stdout→файл ТОЛЬКО под S50): `/run/carthing/carthing-remote.log`.
  keys.json: `/run/carthing-state/carthing/keys.json`. settings: `.../settings.json`.
- rootfs персистентный — hot-deploy переживает ребут.

## 8. ЖИВОЙ ТЕСТ (нужен владелец + iPhone + Fosi) — не выполнен
1. iPhone «забыть Car Thing» + keystore чист → режим сопряжения → пара по BLE.
   Проверить keys.json: ОДНА identity c `ltk`+`irk`+`link_key` (CTKD сработал), айфон не двоится.
2. Выбрать маршрут iPhone→Fosi → Car Thing звонит classic (`A2DP_SOURCE_CLASSIC_DIALED`), айфон
   подхватывает, музыка идёт iPhone→CarThing→Fosi; AMS-метадата живёт.
3. Снять маршрут → `back to BLE-only`, BLE не падает.

## ОБНОВЛЕНИЕ статуса (2026-06-02, продолжение)
- STAGE 2.1 ГОТОВО (коммит): удалены _build_session_plan/_apply_session/VALID_SESSIONS,
  импорт session_presets, файл session_presets.py. Boot чистый.
- STAGE 2.2a ГОТОВО: пункт меню «Сессии и маршруты» → «Маршруты», ведёт на ROUTER-экран
  (active_desktop=ROUTER). Экран режимов (SessionsScreen) теперь НЕДОСТИЖИМ из UI.
  Починен `route_activate` (он шёл через session_select->noop после Stage1; теперь
  re-select входа -> _activate_route). Boot чистый, GUI active.
- STAGE 2.2b ОСТАЛОСЬ (физическое удаление осиротевшего, не user-facing):
  * screens.py: удалить класс `SessionsScreen` (≈241-349) + алиас `ModesScreen = SessionsScreen`.
  * gui_controller.py: убрать импорт `SessionsScreen`; в списке screens[] заменить слот idx3
    (`SessionsScreen(emit=emit)`) на `RouteBuilderScreen(emit=emit)` (НЕ менять индексы!);
    убрать ветки `mode_select`/`session_select` в _nav_intent (125-132) и `session_focus`->
    screens[MODES].tap (репойнтить или убрать); `show_session_screen` -> show ROUTER или удалить.
  * intents.py: убрать `mode_select`/`session_select` (75-78) и `_session_select` (166-170).
  * app_state.py: убрать `active_session`/`_active_session`/`_normalize_session`/`MODES`/`SESSIONS`
    (оставить ROUTER/TRANSFER), `transfer_active` гейтить по маршруту.
  * runtime_model.py: убрать `active_session`/`mode_status`. power_policy: `set_active_session`.
    settings_service: не персистить active_session. carthing_runtime: getattr active_session в
    _on_pairing_failure (стр.~395) — заменить на проверку активного маршрута/source-stream.
  Делать по файлу + py_compile + деплой + рестарт + проверка boot.
