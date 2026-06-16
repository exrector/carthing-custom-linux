# Car Thing как Bluetooth медиа-роутер (результат)

**Что это:** Car Thing превращён из «пульта Spotify» в **Bluetooth-роутер/аудиоинтерфейс**: одно устройство, **один BD-адрес**, **dual-mode** одновременно — BLE (HID/AMS/ANCS к iPhone) и classic A2DP (приём аудио с iPhone и переброс на BT-колонку). Per-peer AVRCP-коммутатор, маршрутизация аудио между источниками и приёмниками. Весь BT-стек — **Bumble на сыром HCI** (`/dev/ttyS1`), **без BlueZ**, без `bluetoothd`, без D-Bus.

Готовый результат: рабочий рантайм роутера + доказательства маршрутных тестов + архитектура.

## Что доказано

- **Dual-mode на одном MAC:** iPhone видит Car Thing и как BLE-аксессуар (HID/медиа-контроль через AMS, нотификации через ANCS), и как classic A2DP-приёмник — одновременно, с одной CTKD-парой.
- **A2DP-мост:** приём A2DP-потока от iPhone и переброс на колонку (напр. Fosi) — Car Thing посередине, прозрачно.
- **Per-peer AVRCP-коммутатор:** раздельный AVRCP на каждого пира, backchannel к колонке, маршрутизация громкости (доказано: ZD3 remote gain «невидим» для BT).
- **Route graph:** мир описан как сервисы (endpoints/capabilities), а не устройства; один и тот же Mac живёт и во Inputs, и в Outputs. Аудио маршрутизируется по графу.

## Исходники (рабочий рантайм)

| Файл | Роль |
|---|---|
| `a2dp_bridge.py` | A2DP приём/переброс, AVRCP-коммутатор, ядро моста |
| `ams_client.py` / `ancs_client.py` | Apple Media Service (контроль медиа) / Apple Notification Center |
| `accessory_orchestrator.py` | оркестрация видимости/режимов (pairing/transfer) |
| `route_graph.py` / `route_planner.py` | граф сервисов и планировщик маршрутов |
| `link_manager.py` / `carthing_link.py` | управление линками/реконнектом |
| `session_runner.py` / `transfer_control.py` / `transfer_service.py` | сессии и переключение источника |
| `virtual_connectors.py` / `virtual_socket.py` | виртуальные коннекторы (абстракция эндпоинтов) |

## Документы (архитектура + доказательства тестов)

| Док | Что |
|---|---|
| `route-graph-architecture-2026-06-01.md` | архитектура графа маршрутов |
| `dual-mode-test-plan-2026-06-10.md` | план тестов dual-mode |
| `fosi-dual-mode-repro-2026-06-04.md` | воспроизведение dual-mode с колонкой Fosi |
| `ios-dual-mode-audio-route-2026-06-05.md` | маршрут аудио iOS dual-mode |
| `route-test-series-results.md` | результаты серии маршрутных тестов |
| `HANDOFF-MODE-REMOVAL-AND-ROUTER-2026-06-02.md` | переход от «режимов» к роутеру |

## Как пользоваться
Файлы кладутся в `/usr/lib/carthing/`, запускаются рантаймом (`carthing_runtime.py`) поверх Bumble на `/dev/ttyS1`. Зависимость — vendored Bumble (в основном образе). Это рабочая основа медиа-роутера, не демо.
