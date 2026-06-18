# Car Thing macOS Observer

Наблюдаемый (observer) хелпер на стороне Mac для **Bluetooth-first session-транспорта**
Car Thing. Это первый deliverable серверной/клиентской части на macOS.

Источник архитектуры:
[`../docs/INPUT-SESSION-OUTPUT-ARCHITECTURE-2026-06-18.md`](../docs/INPUT-SESSION-OUTPUT-ARCHITECTURE-2026-06-18.md).

> **Важно про модель.** Отдельного «режима macOS» нет. Mac — это **multi-role
> endpoint** (`audio_input` / `session_peer` / `remote_mic_receiver` / `usb_peer`)
> внутри Play Now / Коммутатора. `Client ON/OFF` управляет **только** session/client
> plane и не запрещает Mac быть аудиовходом. Audio route plane и session plane
> разделены. Этот хелпер трогает **только session plane** (BLE GATT bootstrap +
> L2CAP CoC), не audio route и не классический A2DP.

## Что это умеет (scaffold)

- BLE-скан по сервису Car Thing → connect → GATT bootstrap → открытие L2CAP CoC по
  динамическому PSM.
- Бинарный протокол **CTSP** (кадры hello/capabilities/status/route_state/command/
  audio_pcm16/telemetry/error) — кодек с тестами.
- Живой observer-UI (SwiftUI): обнаружение/pairing/bootstrap/CoC статус, bytes/sec,
  frame/sec, latency estimate, last frame/seq, mic idle/active, route/session state,
  лог, кнопки connect/disconnect/scan, Client ON/OFF, Rec WAV, Save diagnostic bundle.
- Persisted реестр endpoint'ов (`~/Library/Application Support/CarThingObserver/endpoints.json`).
- Приём remote-mic PCM16 16k mono → ring buffer + debug WAV (только on-demand).

Никаких облачных зависимостей, никаких платных сервисов, **никакого
BlueZ/bluetoothd/bluetoothctl/sdptool** — только нативный Apple CoreBluetooth.

## Модули

| Модуль | Назначение | Зависимости |
|---|---|---|
| `ProtocolCore` | Кодек кадров CTSP, версии, seq, типы кадров | Foundation (чистый, тестируемый headless) |
| `DeviceRegistry` | Стабильная identity CarThing endpoint, persisted pairing/session metadata | ProtocolCore |
| `SessionState` | Состояние соединения/маршрута, client on/off, ошибки, метрики | ProtocolCore |
| `AudioPipeline` | Приём PCM16 16k mono, ring buffer, debug WAV | Foundation |
| `TransportCore` | CoreBluetooth scan/connect/GATT bootstrap/L2CAP CoC stream | ProtocolCore, SessionState, DeviceRegistry |
| `ObserverApp` | SwiftUI observer-окно (исполняемый таргет) | все выше |

## Сборка и запуск

Требуется macOS 13+, Swift 6 toolchain (есть `/usr/bin/swift`).

### Тесты кодека (без устройства, без Bluetooth)

```sh
swift test
```

### Просто собрать всё

```sh
swift build
```

### Запустить observer

Рекомендуемый путь — собрать `.app` (TCC привяжет разрешение Bluetooth к bundle id):

```sh
./build-app.sh            # release по умолчанию
open .build/release/CarThingObserver.app
```

Быстрый dev-запуск (Info.plist встроен в бинарь, TCC-промпт тоже сработает):

```sh
swift run CarThingObserver
```

При первом запуске macOS спросит разрешение на Bluetooth — нужно подтвердить
(System Settings → Privacy & Security → Bluetooth).

## CTSP — формат кадра

Заголовок 16 байт, multi-byte поля в big-endian (network order):

```text
magic:   4 bytes  "CTSP"
version: 1 byte
type:    1 byte
flags:   2 bytes
seq:     4 bytes
len:     4 bytes
payload: len bytes
```

Типы кадров и их байтовые коды — в
[`Sources/ProtocolCore/CTSPFrameType.swift`](Sources/ProtocolCore/CTSPFrameType.swift).
Это **источник истины**: device-side (Bumble на QN19) должен использовать те же коды.

## BLE GATT-контракт

Определён в [`Sources/TransportCore/GATTContract.swift`](Sources/TransportCore/GATTContract.swift).
Тоже **источник истины** для device-side. GATT используется только для bootstrap;
session/data идёт по L2CAP CoC.

| Характеристика | UUID | Доступ | Назначение |
|---|---|---|---|
| Service | `C7C50000-…` | — | сервис session-транспорта |
| protocol_version | `C7C50001-…` | read | версия CTSP устройства |
| capabilities | `C7C50002-…` | read | роли/транспорты/audio форматы |
| endpoint_id | `C7C50003-…` | read | стабильный id endpoint |
| current_psm | `C7C50004-…` | read+notify | текущий динамический L2CAP CoC PSM (UInt16 LE) |
| client_toggle | `C7C50005-…` | write | 1=client on, 0=off (session plane) |
| status | `C7C50006-…` | notify | краткий статус (полный — по CoC) |

## Известные ограничения (known limitations)

- **Device-side ещё не существует.** BLE GATT-сервис и L2CAP CoC listener на QN19
  пока не реализованы — этот хелпер задаёт контракт, который устройство должно
  реализовать (порядок работ — раздел «Implementation order» в архитектурном доке).
  До этого UI поднимется, скан пойдёт, но bootstrap/CoC не завершатся, пока
  устройство не публикует сервис.
- **Реальный L2CAP CoC ещё не прогонялся вживую** между QN19 и этим хелпером
  (шаг 5 «Implementation order»). I/O-путь стрима написан, но не подтверждён на
  железе.
- **route_state** парсится как JSON-снимок `SessionSnapshot`; финальный бинарный
  формат route_state ещё не зафиксирован с device-side.
- **latency estimate** — это RTT одиночного hello-рукопожатия на открытии CoC,
  не непрерывный пинг (резус-политика запрещает агрессивный polling).
- **HFP не реализован** — это research fallback по архитектуре, не основной путь
  remote mic. Основной путь: ALSA/PDM capture на устройстве → PCM16 → CoC.
- Reliability/ack-слой CTSP (`needsAck` флаг) зарезервирован, но не реализован.
- Без подписи Developer ID; ad-hoc подпись в `build-app.sh` достаточна для
  локального запуска, но Gatekeeper может ругаться при переносе на другой Mac.

## Ресурсная политика (инвариант)

Хелпер уважает «тихий Play Now»:

- скан — только по явному действию (`Scan`), не фоновый и не постоянный;
- GATT bootstrap может прочитать identity/PSM после явного connect, но L2CAP/CTSP
  session открывается только при `Client ON`;
- `Client OFF` закрывает L2CAP/CTSP и оставляет session plane тихим;
- remote mic не стримится, пока устройство не пошлёт `audio_pcm16` (по команде);
- WAV пишется только по кнопке `Rec WAV`.
