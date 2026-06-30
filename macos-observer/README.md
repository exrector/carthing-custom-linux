# CarThingBTLink

Минимальный macOS helper для микрофона Car Thing. Он работает в фоне и не
меняет системный input/output macOS:

```text
Car Thing PDM microphones
  -> HCIC gain + SpeexDSP
  -> BLE GATT bootstrap
  -> Bluetooth LE L2CAP CoC (CTSP, Opus VOIP 16 kHz / 60 ms)
  -> CarThingBTLink.app
  -> managed Whisper/Assistant worker
  -> live partial text on Car Thing
  -> live text and responses back over the same Bluetooth CTSP session
```

Bluetooth обслуживается только нативным CoreBluetooth. BlueZ, HFP, Loopback и
встроенный микрофон Mac в этом тракте не используются.

## Состав

- `CarThingBTLink` - единое приложение с нативным GUI: CoreBluetooth, CTSP,
  Opus, локальный audio pipe, lifecycle Whisper/Assistant worker и управление
  внешними экранными модулями.
- `ServerPlugins` - подключаемые серверные модули. По умолчанию активен
  `mac_music`: он передаёт локальную Apple Music-сессию и принимает media-команды.
- `TransportCore` - scan, connect, GATT bootstrap и L2CAP CoC.
- `ProtocolCore` - потоковый кодек CTSP.
- `install-btlink-app.sh` - release build, подпись, установка `.app` и LaunchAgent.
- `launchd/com.carthing.btlink.plist` - шаблон LaunchAgent.
- `../plugin-sdk` - публичный JSONL API, упаковщик `.ctplugin` и независимый
  пример Mac Deck.
- `carthingctl` - status, logs, file upload и restart через Bluetooth CTSP.

## Установка

```sh
./install-btlink-app.sh
```

Скрипт собирает и подписывает
`~/Applications/CarThingBTLink.app`, устанавливает
`~/Library/LaunchAgents/com.carthing.btlink.plist` и запускает один экземпляр
приложения. Оно само запускает и контролирует Assistant worker; отдельный
`com.carthing.btwhisper` удаляется. Opus runtime копируется внутрь `.app`.
При первом запуске macOS запрашивает Bluetooth для приложения, а Terminal в
рабочем цикле не участвует. При первом чтении Apple Music приложение также
запросит Automation-доступ к Music.

Список серверных модулей задаётся одной переменной окружения:

```sh
CARTHING_SERVER_PLUGINS=mac_music
```

Модули реализуют `ServerPlugin` и подключаются через `ServerPluginManager`.
HomePod/AirPlay остаётся внешним provider ассистента; координатор отдаёт ему
приоритет, а при отсутствии активного AirPlay автоматически показывает
локальную Music-сессию Mac.

Внешние экранные модули не компилируются с приложением. Пользователь
устанавливает архив `.ctplugin` во вкладке «Модули», отдельно включает его, и
его карточки появляются в четвёртом фиксированном view Car Thing. Transport
каталога, snapshot и touch-action идёт только по CTSP Bluetooth. Полный
контракт: `../plugin-sdk/README.md`.

## Bluetooth maintenance

После однократного provisioning дальнейшие изменения Python runtime можно
доставлять без USB:

```sh
../scripts/provision-bluetooth-maintenance.sh
carthingctl status
carthingctl logs 100
../tools/deploy-bt usr/lib/carthing/screens.py --restart
```

Файлы передаются подтверждаемыми блоками по тому же L2CAP CoC, проверяются
SHA-256 и заменяются атомарно. Подробный контракт и ограничения находятся в
`../docs/bluetooth-maintenance.md`.

## Проверка

```sh
swift test
swift build -c release
launchctl print gui/$(id -u)/com.carthing.btlink
tail -f /private/tmp/carthing-btlink.err
```

Рабочий лог содержит последовательность `l2cap_open`,
`streaming_mic=on`, затем возрастающий `audio_frames`.

## Протокол

CTSP использует 16-байтовый big-endian заголовок:

```text
magic:   4 bytes  "CTSP"
version: 1 byte
type:    1 byte
flags:   2 bytes
seq:     4 bytes
len:     4 bytes
payload: len bytes
```

GATT UUID-контракт находится в
`Sources/TransportCore/GATTContract.swift`. GATT передаёт PSM и включает client;
аудио и команды идут по L2CAP CoC.

При `SIGTERM` helper сначала отправляет `stop_mic` и `disconnect`, затем закрывает
CoreBluetooth-соединение. После потери канала он автоматически сканирует и
восстанавливает соединение.
