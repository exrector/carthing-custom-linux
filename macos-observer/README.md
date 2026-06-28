# CarThingBTLink

Минимальный macOS helper для микрофона Car Thing. Он работает в фоне и не
меняет системный input/output macOS:

```text
Car Thing PDM microphones
  -> BLE GATT bootstrap
  -> Bluetooth LE L2CAP CoC (CTSP, IMA ADPCM)
  -> CarThingBTLink
  -> 127.0.0.1:49500
  -> voice-assistant/bt_whisper.py
```

Bluetooth обслуживается только нативным CoreBluetooth. BlueZ, HFP, Loopback и
встроенный микрофон Mac в этом тракте не используются.

## Состав

- `CarThingBTLink` - headless LaunchAgent, Bluetooth-транспорт и локальный TCP.
- `TransportCore` - scan, connect, GATT bootstrap и L2CAP CoC.
- `ProtocolCore` - потоковый кодек CTSP.
- `install-btlink-app.sh` - release build, подпись, установка `.app` и LaunchAgent.
- `launchd/com.carthing.btlink.plist` - шаблон LaunchAgent.

## Установка

```sh
./install-btlink-app.sh
```

Скрипт собирает и подписывает
`~/Applications/CarThingBTLink.app`, устанавливает
`~/Library/LaunchAgents/com.carthing.btlink.plist` и запускает один экземпляр
helper. При первом запуске macOS может запросить доступ к Bluetooth.

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
