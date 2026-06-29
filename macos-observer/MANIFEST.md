# MANIFEST — Car Thing macOS Observer

Журнал всех файлов и артефактов, созданных Claude в рамках работы над macOS
observer/helper. Назначение: передать Codex полный список «что и зачем», чтобы
он понимал, что появилось рядом с его рабочей веткой.

**Файл append-only.** Новые записи дописываются снизу в раздел «Журнал
изменений», старые не переписываются.

---

## Границы работы (рамки Claude)

- Вся работа изолирована в подпапке **`macos-observer/`**. Ни один файл вне этой
  папки не создавался и не изменялся.
- На момент работы устройство Car Thing в **активной BT-сессии Codex**. Поэтому
  observer **НЕ инициирует BT-операции автоматически**: scan/connect/openL2CAP
  происходят только по явному нажатию кнопок в UI. Запуск приложения сам по себе
  ничего в эфир не шлёт и не сканирует.
- Git: работа ведётся на ветке Codex (`state-on-p2`), но вся папка
  `macos-observer/` — **untracked**. Tracked-файлы Codex не затронуты. Claude
  **не делал** commit/add/push в ветку Codex.
- Runtime-артефакты (diagnostic bundle, debug WAV, реестр endpoint'ов) пишутся
  **не** в репо и **не** в `~/Downloads`/`/tmp`, а в единую контролируемую папку
  (см. ниже).

## Где живут runtime-артефакты (создаются при ЗАПУСКЕ приложения, не в репо)

| Артефакт | Путь по умолчанию | Переопределение |
|---|---|---|
| Реестр endpoint'ов | `~/Library/Application Support/CarThingObserver/endpoints.json` | — |
| Diagnostic bundle | `~/Library/Application Support/CarThingObserver/artifacts/carthing-diag-<ts>/` | `CARTHING_OBSERVER_ARTIFACTS` |
| Debug WAV | `~/Library/Application Support/CarThingObserver/artifacts/carthing-mic-<ts>.wav` | `CARTHING_OBSERVER_ARTIFACTS` |
| Build output | `macos-observer/.build/` (gitignored) | — |
| `.app` bundle | `macos-observer/.build/release/CarThingObserver.app` (gitignored) | — |

Чтобы держать артефакты прямо в своей папке:
`export CARTHING_OBSERVER_ARTIFACTS="$PWD/artifacts"` перед запуском.

---

## Реестр исходных файлов (созданы Claude, в репо)

### Корень пакета
| Файл | Назначение |
|---|---|
| `Package.swift` | SwiftPM-манифест: 6 модулей + тест-таргет + встраивание Info.plist в бинарь |
| `README.md` | Описание, сборка/запуск, CTSP-формат, GATT-контракт, known limitations |
| `MANIFEST.md` | Этот журнал |
| `.gitignore` | Игнор `.build/`, `.swiftpm/`, `artifacts/`, `.DS_Store` и пр. |
| `build-app.sh` | Сборка `.app`-бандла вокруг SwiftPM-бинаря + ad-hoc codesign (для TCC Bluetooth) |

### Sources/ProtocolCore — кодек CTSP (чистый Foundation, тестируемый headless)
| Файл | Назначение |
|---|---|
| `CTSPFrameType.swift` | Enum типов кадров (hello/capabilities/status/route_state/command/audio_pcm16/telemetry/error) — источник истины байтовых кодов для device-side |
| `CTSPFrame.swift` | Структура кадра + флаги |
| `CTSPCodec.swift` | Энкодер + потоковый декодер (буферизация фрагментов L2CAP, защита payload-лимитом), константы протокола |

### Sources/DeviceRegistry — identity и persistence
| Файл | Назначение |
|---|---|
| `Endpoint.swift` | Multi-role endpoint: роли, транспорты, identity (USID/MAC/BT/USB), policy (session/audio plane раздельно) |
| `DeviceRegistry.swift` | JSON-persist реестр endpoint'ов в Application Support |

### Sources/SessionState — состояние и метрики
| Файл | Назначение |
|---|---|
| `RouteModel.swift` | Enum'ы DeviceMode/AudioInput/OutputSink/SessionPhase/TransportPhase + `SessionSnapshot` (RouteGraph) |
| `TransportMetrics.swift` | `TransportMetrics` + `MetricsAccumulator` (скорости по окну 1 c) |

### Sources/AudioPipeline — remote mic
| Файл | Назначение |
|---|---|
| `AudioPipeline.swift` | Приём PCM16 16k mono → ring buffer + debug WAV + RMS-уровень. Сам захват НЕ запускает |

### Sources/TransportCore — CoreBluetooth (только macOS)
| Файл | Назначение |
|---|---|
| `GATTContract.swift` | UUID сервиса и характеристик Car Thing — источник истины для device-side (Bumble на QN19) |
| `TransportEvent.swift` | Типы событий транспорта + `DiscoveredPeripheral` |
| `TransportCore.swift` | CBCentralManager: scan→connect→GATT bootstrap→openL2CAPChannel→CoC I/O. Все callbacks на main |

### Sources/ObserverApp — SwiftUI (исполняемый таргет)
| Файл | Назначение |
|---|---|
| `ObserverApp.swift` | `@main` App + revealInFinder |
| `AppModel.swift` | ObservableObject: связывает события TransportCore → SessionSnapshot/Metrics, кормит AudioPipeline, лог, diagnostic bundle, резолв artifacts-папки |
| `ContentView.swift` | Окно наблюдения: транспорт/маршрут/метрики/контролы/лог |
| `Info.plist` | Bundle-метаданные + `NSBluetoothAlwaysUsageDescription` (для TCC) |

### Tests/ProtocolCoreTests
| Файл | Назначение |
|---|---|
| `CTSPCodecTests.swift` | 11 тестов кодека CTSP (round-trip, фрагментация, склейка, ошибки) — `swift test` без устройства |

---

## Журнал изменений

### 2026-06-18 (сессия 1) — создание scaffold
- Создан SwiftPM-пакет `macos-observer/` с 6 модулями (см. реестр выше).
- 18 исходных файлов + Package.swift/README/build-app.sh/.gitignore.
- `swift build` — OK; `swift test` — 11/11 OK.
- `./build-app.sh` → `.app` с встроенным Info.plist (проверено `otool __info_plist`).
- Никаких BT-операций с устройством не выполнялось.

### 2026-06-18 (сессия 2) — изоляция артефактов + журнал
- `AppModel.swift`: добавлен `artifactsDir` (env `CARTHING_OBSERVER_ARTIFACTS` ??
  Application Support/CarThingObserver/artifacts). Diagnostic bundle и WAV больше
  **не** пишутся в `~/Downloads` и `/tmp`.
- `.gitignore`: добавлен `artifacts/`.
- Создан этот `MANIFEST.md`.
- `swift build` — OK после правок.
- Подтверждено: вся `macos-observer/` untracked на ветке `state-on-p2`,
  tracked-файлы Codex не затронуты, commit/push не делались.

### 2026-06-18 (сессия 3) — стенд связки клиент-сервер на Mac (без устройства)
Контекст: Codex в лимитах ~3 часа. Решено НЕ трогать устройство (единственный
HCI `/dev/ttyS1` занят роутером Codex — второй listener = «HCI busy» = поломка
живой сессии). Вся проверка связки клиент-сервер делается loopback'ом на Mac.

Новые файлы (все с шапкой-пометкой про тесты клиент-сервер):
- `Sources/ProtocolCore/SessionLink.swift` — абстракция транспорта (байтовый канал).
- `Sources/ProtocolCore/CTSPSession.swift` — движок CTSP поверх SessionLink (seq,
  decode, callbacks), переиспользуется клиентом и mock-сервером.
- `Sources/LinkKit/TCPSessionLink.swift` — TCP-реализации SessionLink (клиент + сервер) на Network.framework.
- `Sources/LinkKit/MockCarThingServer.swift` — ⚠️ ВРЕМЕННЫЙ эмулятор device-side по CTSP.
- `Sources/CTSPProbe/main.swift` — ⚠️ ВРЕМЕННЫЙ CLI: поднимает mock-сервер + клиент, печатает метрики.
- `Tests/IntegrationTests/ClientServerTests.swift` — интеграционные тесты связки по реальному сокету.
Правки Package.swift: добавлены таргеты `LinkKit`, `CTSPProbe`, `IntegrationTests`.

Результаты прогона (Mac-only, устройство не затронуто):
- `swift test` — 15/15 OK (11 кодек + 4 интеграционных по реальному TCP-сокету).
- `swift run CTSPProbe` — связка клиент-сервер прошла end-to-end:
  bootstrap (capabilities+route_state), RTT hello ≈ 0.8 мс, on-demand mic 50 кадров/с
  ~32.8 КБ/с, RMS 0.213 (синтетический тон), route_state connected→streamingMic,
  96000 б PCM = 3 c при 32 КБ/с, stop_mic останавливает поток.
- Проверено: `git status` всего репо = только `macos-observer/` (untracked),
  ничего вне папки, commit/push не делались, BT/HCI устройства не трогались.

⏳ НЕ СДЕЛАНО (ждёт решения владельца, риск для сессии Codex):
- реальный BLE L2CAP CoC между Mac и устройством — требует device-side listener
  на том же HCI `/dev/ttyS1`, что занят роутером Codex («HCI busy» = поломка).
  Деплой тестового CTSP-listener на устройство — только по явному «да» владельца.

### 2026-06-18 (сессия 4) — реальный device-side тест по TCP/usb0 (БЕЗ hci0)
Владелец дал «да» на деплой. Разведка показала: hci0 — единственный контроллер,
занят `carthing_runtime.py` Codex → радио НЕ трогаем. Device-side CTSP протестирован
по TCP поверх usb0.

Новые файлы на Mac (с шапками-пометками):
- `device/ctsp_test_server.py` — ⚠️ ВРЕМЕННЫЙ эталонный device-side CTSP-сервер
  (Python stdlib, TCP, без BT). Деплоится на устройство.
- `scripts/device-ctsp-test.sh` — ⚠️ ВРЕМЕННЫЙ деплой/запуск/останов/очистка device-сервера.
- `Sources/CTSPProbe/main.swift` — обновлён: добавлен режим удалённого клиента
  `swift run CTSPProbe <host> <port>`.

Файлы на устройстве и полный лог прогона → **DEVICE-DEPLOY-LOG.md**.
Итог: Mac↔QN19 связка работает (RTT 4.32 мс, mic 41 кадр/с, тон принят);
после теста сервер остановлен, сессия Codex (1110/hci0/btattach 361) не задета.

### 2026-06-18 22:03 MSK — Codex acceptance pass: Client OFF действительно тихий
Контекст: после приёмки scaffold обнаружено архитектурное расхождение с моделью
владельца: `Client ON/OFF` должен управлять только session/client plane, но при
выключенном клиенте не должно быть L2CAP/CTSP session-шума. В исходном scaffold
`TransportCore` открывал L2CAP CoC сразу после получения `current_psm`.

Правка Codex:
- `TransportCore.swift`: GATT bootstrap теперь только публикует identity/PSM;
  `openL2CAPChannel` вызывается только когда включён `Client ON`.
- `TransportCore.swift`: `Client OFF` закрывает открытый L2CAP/CTSP channel и
  возвращает транспорт в фазу `bootstrapped`, если PSM уже известен.
- `AppModel.swift`: выключение client сбрасывает session phase в `off`, гасит
  mic-active индикацию; `l2capClosed` теперь уважает `clientEnabled`.
- `README.md`: ресурсная политика уточнена — GATT bootstrap допустим после
  явного connect, но CTSP session открывается только при `Client ON`.

Проверки после правки:
- `swift test` — 15/15 OK.
- `swift run CTSPProbe` — Mac-only loopback end-to-end OK: hello RTT, route_state,
  on-demand mic stream ~50 fps, stop_mic.
- Устройство не перепрошивалось и рабочий BT/HCI не трогался.
- `./build-app.sh` — release `.app` собран и ad-hoc подписан:
  `.build/release/CarThingObserver.app`.

### 2026-06-28 — минимальный рабочий CarThingBTLink

Записи выше сохранены как исторический журнал. Текущий источник истины —
`README.md` и `Package.swift`.

- Удалены ObserverApp, DeviceRegistry, SessionState, AudioPipeline, LinkKit,
  CTSPProbe, временный TCP device server и старый `build-app.sh`.
- Оставлены только `CarThingBTLink`, `TransportCore`, `ProtocolCore` и 11 тестов
  CTSP-кодека.
- Добавлен `install-btlink-app.sh`: release build, подпись, установка `.app`,
  конфигурация и запуск LaunchAgent.
- Реальный тракт подтверждён на устройстве:
  `PDM/ALSA -> HCIC/SpeexDSP -> Opus VOIP 16 kHz/60 ms -> BLE L2CAP CoC
  -> Apple DictationTranscriber -> live partial text`.
- Подтверждены штатное закрытие, повторное подключение без зависшего CID и
  непрерывный поток аудиокадров после перезапуска helper.
