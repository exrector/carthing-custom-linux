# Задача: Написать универсальный iAP2-агент для Car Thing

## Контекст

**Устройство:** Spotify Car Thing (Superbird, Amlogic S905D2, Buildroot Linux)
**Цель Slot A:** Превратить Car Thing в Bluetooth-пульт для устройств Apple (iPhone, iPad, Mac)

## Текущая ситуация

### Что уже работает
- **bt_agent.py** — Bluetooth pairing agent (NoInputNoOutput, автоподтверждение)
- **avrcp_ctrl.py** — Кнопки и энкодер → AVRCP PASS_THROUGH на Mac (Play/Pause, Next, Prev, Vol ±)
- **bluetoothd** (BlueZ 5.49) — запущен с плагинами: gap, deviceinfo, a2dp

### Проблема
- **AVRCP работает только с Mac.** iPhone/iPad не подключаются через AVRCP — Apple требует **iAP2** (iPod Accessory Protocol 2) для обмена метаданными и управления.
- **qt-superbird-app** (3.2 MB, стоковое приложение Spotify) умеет регистрировать iAP2 SDP запись через BlueZ ProfileManager1. Он работает, но:
  - Тянет Qt, Sensory SDK, WAMP сервер — всё это не нужно
  - Падает при каждом цикле Sensory SDK (нет .snsr файлов)
  - Запущен через watchdog-скрипт (перезапуск каждые 3 сек после падения)

### Что пробовали
| Подход | Результат |
|--------|-----------|
| `iap2_agent.c` (libdbus-1, 5692 байт) | D-Bus объект регистрируется, но BlueZ не создаёт SDP запись |
| `gdbus call RegisterProfile` | Возвращает `()` (успех), но SDP запись НЕ появляется |
| `sdptool add` | Не поддерживает кастомные UUID в BlueZ 5.49 |
| RFCOMM socket на канале 1 | Socket открывается, но BlueZ не связывает его с SDP |

## Что нужно получить

**Единый универсальный агент** для всех Apple-устройств:

### Функциональность

| Функция | Описание |
|---------|----------|
| **Управление воспроизведением** | Play/Pause, Next Track, Previous Track |
| **Метаданные** | Название трека, исполнитель, альбом |
| **Обложка альбома** | Получение и отображение artwork |
| **Громкость** | Volume Up/Down |
| **Универсальность** | Работает с iPhone, iPad, Mac — без перенастройки |

### Техническое описание

Агент должен:

1. **Зарегистрировать iAP2 SDP запись** в BlueZ через ProfileManager1.RegisterProfile
   - UUID: `00000000-deca-fade-deca-deafdecacaff`
   - RFCOMM Channel: 1
   - ServiceRecord с полным XML

2. **Принимать входящие iAP2-соединения** от iPhone/iPad/Mac
   - Обрабатывать iAP2 протокол (Command/Response)
   - Отправлять события нажатий кнопок (Play, Pause, Next, Prev)
   - Запрашивать и получать метаданные (Now Playing)
   - Запрашивать и получать обложки (Artwork)

3. **Пересылать команды** из iAP2 в систему
   - Кнопки/энкодер → iAP2 команда → Apple-устройство
   - Метаданные от Apple-устройства → вывод на экран Car Thing (480×800)

## Ограничения устройства

### Что ЕСТЬ
- **Python 3.7** (без dbus модуля, но есть ctypes)
- **libdbus-1.so.3** (динамическая библиотека)
- **gdbus** (CLI для D-Bus)
- **bluetoothd 5.49** с плагинами: gap, deviceinfo, a2dp
- **gcc** можно использовать через Docker (arm32v7/debian:bullseye)
- **Экран:** 480×800, DRM `/dev/dri/card0`
- **Тачскрин:** event3 (TLSC6x)
- **Энкодер:** event1 (EV_REL, code=6)
- **Кнопки:** event0 (gpio-keys, коды 2-5, 28, 50)

### Чего НЕТ
- **Нет gcc на устройстве** (нужна кросс-компиляция)
- **Нет python-dbus** (только ctypes к libdbus-1)
- **Нет WiFi** (устройство подключено только к питанию через USB)
- **Нет интернета** (телеметрия невозможна)
- **Нет systemd** (BusyBox init + supervisord)
- **Нет X11/Wayland** (Weston запущен, но Chromium — заглушка)

### Известная проблема с BlueZ 5.49
BlueZ 5.49 создаёт SDP запись ТОЛЬКО когда:
1. D-Bus объект Profile1 зарегистрирован на нужном пути
2. Вызван ProfileManager1.RegisterProfile с правильными параметрами
3. **Профиль реально открывает RFCOMM socket и слушает** — SDP создаётся автоматически при bind/listen

Проблема: вызов RegisterProfile через `gdbus call` возвращает успех `()`, но SDP запись не появляется в `sdptool browse local`. qt-superbird-app делает это через свой внутренний D-Bus код (libdbus C API) и SDP появляется.

## Ключевая подсказка

В результате реверс-инжиниринга qt-superbird-app найдено:
- Регистрация идёт через `org.bluez.Profile1` интерфейс
- iAP2 UUID: `00000000-deca-fade-deca-deafdecacaff`
- RFCOMM канал: 1
- ServiceRecord XML содержит атрибуты 0x0001 (UUID), 0x0004 (протоколы L2CAP+RFCOMM), 0x0009 (версия профиля), 0x0100 (имя "iAP2")

qt-superbird-app делает это так:
1. Регистрирует D-Bus объект на `/org/bluez/profile/iap2` с vtable для Profile1
2. Открывает RFCOMM socket, bind на BDADDR_ANY + channel 1, listen
3. Вызывает RegisterProfile через D-Bus C API (не через subprocess)
4. BlueZ видит listening socket и создаёт SDP запись

Наш iap2_agent.c делал шаги 1 и 2, но RegisterProfile через subprocess (dbus-send) не работал — не мог передать dict с вложенными variant'ами.

## Что должен сделать агент

### Минимальный вариант (только SDP)
Написать программу (C или Python через ctypes), которая:
1. Регистрирует D-Bus объект Profile1
2. Открывает и слушает RFCOMM на канале 1
3. **Корректно вызывает RegisterProfile через D-Bus C API** (не subprocess!)
4. Принимает входящие соединения и отвечает на iAP2 команды

### Полный вариант (медиа-пульт)
Всё из минимального + обработка iAP2 протокола:
- Отправка кнопочных событий (Play/Pause/Next/Prev/Vol)
- Запрос Now Playing Information (название, артист, альбом)
- Запрос Artwork (обложка альбома)
- Вывод метаданных на экран Car Thing

## Формат ответа

Агент должен предоставить:
1. **Готовый рабочий код** (C или Python) который регистрирует iAP2 SDP
2. **Инструкцию по компиляции** (через Docker arm32v7/debian:bullseye)
3. **Пример обработки iAP2 команд** (Play/Pause, Now Playing)
4. **Интеграцию с существующим кодом** (avrcp_ctrl.py уже обрабатывает кнопки — нужно связать)

## Файлы проекта

Все файлы в `slot_a/` проекта `carthing-remote`:
- `bt_agent.py` — Bluetooth pairing agent (не трогать, работает)
- `avrcp_ctrl.py` — Кнопки → AVRCP (не трогать, работает с Mac)
- `iap2_agent.c` — Попытка замены (не работает, SDP не создаётся)
- `register_iap2.py` — Попытка через gdbus (не работает)
- `start_superbird.sh` — Watchdog для qt-superbird-app (временное решение)

## Ссылки

- RE артефакты qt-superbird-app: `~/Downloads/qt-superbird-app.re/`
- Бинарник: `~/Downloads/qt-superbird-app`
- Документация проекта: `NOTES.md` (разделы "Замена qt-superbird-app", "Восстановление Bluetooth")
