# GUI: модульный compositor PIL→DRM (результат)

**Что это:** собственный графический слой Car Thing, рисующий **напрямую в DRM** (`/dev/dri/card0`), без LVGL и без веб-киоска. Субстрат — **PIL → DRM**, модульный compositor со словарём компонентов, тема «Терминал», на штатной панели **480×800**. Нативный поворот кадра вынесен в `libcarthing_frame.so`. Рендер-цикл снят с BT event-loop, чтобы кадры не блокировали стек.

Готовый результат: рабочий GUI-рантайм + архитектура.

## Что доказано

- **Прямой вывод в DRM:** dumb-буфер 480×800, `CRTC set — display active`, `GUI active (modular Compositor)` — на живом устройстве.
- **Модульность:** экраны/компоненты/статусбар/анимации как отдельные модули (словарь компонентов), а не монолит.
- **Нативный поворот:** `libcarthing_frame.so` (`Display: native frame rotator active`) — поворот кадра без тормозов на Python.
- **Развязка с BT:** периодический рендер вынесен с event-loop BT (был доказанный блокер 77-92 мс/кадр); добавлен render-time probe и 2fps cap в потоке.
- **Тема «Терминал»:** ретро-мейнфрейм в палитре exrector.com; тёмная тема/переключатель позже убраны (одна тема).

> Решение по субстрату: **LVGL и веб-киоск отклонены**. GUI = PIL→DRM, модульно.

## Исходники (рабочий GUI)

| Файл | Роль |
|---|---|
| `drm_display.py` | вывод в DRM: коннектор, CRTC, dumb-буфер 480×800 |
| `gui_controller.py` | контроллер GUI / compositor |
| `screens.py` | экраны (Play Now, настройки, картотека и т.д.) |
| `ui_components.py` / `ui_screen.py` / `ui_statusbar.py` / `ui_anim.py` | словарь UI-компонентов, базовый экран, статусбар, анимации |
| `ui_theme.py` | тема «Терминал» (палитра, CRT-постэффекты) |
| `mac_display.py` / `web_display.py` | альтернативные дисплей-бэкенды (разработка/отладка) |
| `libcarthing_frame.so` | нативный поворот кадра |

## Документы
- `docs/gui-runtime-integration-2026-05-22.md` — интеграция compositor в рантайм, грабли и рецепты (поток данных AMS→AppState→compositor, маппинг play/pause→TOGGLE, ввод через input_handler).

## Как пользоваться
Файлы в `/usr/lib/carthing/`, поднимаются `carthing_runtime.py`. Если импорт GUI или DRM-setup падает — рантайм продолжает headless (это штатный fallback). Нужен рабочий PIL (с `ImageFont`).
