# Input / Session / Output Architecture for macOS Transport

Дата: 2026-06-18.

Статус: **актуальный источник для Claude** по теме macOS server/client,
Bluetooth-first transport и первичной пары с Mac.

Этот документ заменяет архитектурную предпосылку из
[`SESSION-OVER-TRANSPORTS-PLAN-2026-06-18.md`](SESSION-OVER-TRANSPORTS-PLAN-2026-06-18.md),
где macOS рассматривался как отдельный режим устройства. Это больше не
актуально.

## Главное решение

Отдельного режима `macOS` нет.

Car Thing остаётся устройством с режимами:

- `Play Now` — дефолтный режим, главный аудиовход обычно iPhone.
- `Коммутатор` — явный режим выбора входов и выходов.
- `Резерв` / USB — отдельная резервная ветка, включается по физическому/USB
  контексту.

macOS внутри этой модели является **multi-role endpoint**, а не режимом:

- `audio_input` — Mac как источник звука для Car Thing.
- `session_peer` / `session_server` — Mac как сервер состояния, команд,
  metadata, assistant-интеграции и diagnostics.
- `remote_mic_receiver` — Mac принимает микрофонный поток с Car Thing.
- `usb_peer` — Mac как проводной peer, если USB data path реально доступен.

Эти роли независимы. Один и тот же Mac может быть только audio input, только
session peer, обеими ролями сразу, или известным, но неактивным endpoint.

## Почему начинать надо с устройства

Car Thing является коммутатором не только выходов, но и входов. Поэтому
серверная часть на Mac не должна первой диктовать модель. Сначала на устройстве
нужны три независимых слоя:

- `InputSource` — аудиоисточники: iPhone A2DP, Mac Bluetooth audio, USB audio,
  local ALSA/PDM/test sources.
- `SessionSource` — non-audio/session источники: Mac server, remote mic session,
  status/control/assistant channel, diagnostics.
- `OutputSink` — аудиовыходы: локальный T9015/line-out, Bluetooth speaker
  output, USB audio output, будущие sinks.

`RouteGraph` должен хранить минимум:

- `active_audio_input`
- `active_output_sink`
- `active_session_sources`
- `client_enabled`
- `transport_state`

Ключевой продуктовый сценарий: в `Play Now` iPhone может оставаться главным
аудиовходом, а Mac параллельно держит session/control/remote-mic канал, если
клиент включён.

## Client ON/OFF

`Client ON/OFF` управляет только session/client plane.

Когда client выключен:

- нет session connect;
- нет heartbeat;
- нет remote-mic streaming;
- нет status push на Mac;
- нет background protocol chatter.

Но это **не** запрещает Mac быть выбранным как audio input. Audio route plane и
session plane должны быть разделены.

## Bluetooth-first transport decision

Приоритет: Bluetooth. USB остаётся вторым путём, когда провод реально подключён
и MAX20332 / USB gadget state подтверждают data path.

Рекомендуемая транспортная матрица:

| Слой | Использовать | Для чего | Не использовать для |
|---|---|---|---|
| BLE GATT | Да | discovery, capabilities, protocol version, endpoint identity, PSM bootstrap, client toggle/status | audio stream, bulk data |
| BLE L2CAP CoC | Да, основной канал | session/data stream, status, commands, remote mic PCM, diagnostics | hi-fi stereo, video, large bulk |
| Classic A2DP/AVRCP | Только audio role | Mac как audio input/output, если выбран route | session/control protocol |
| Classic RFCOMM/custom L2CAP | Lab/fallback | если BLE CoC не выдержит реальный throughput | базовый путь по умолчанию |
| HFP | Research fallback | системный Bluetooth microphone на Mac, если понадобится доказать | основной remote mic путь |
| USB NCM/UAC/storage | Да, secondary/reserve | проводной high-bandwidth/rescue/audio gadget/storage | Bluetooth-first default |

## Pairing contract

Первая нормальная пара с macOS должна сразу создавать не "подключённый Mac", а
multi-role endpoint.

Минимальная модель endpoint:

```text
Endpoint {
  id: stable endpoint id
  kind: macos
  identity:
    carthing_usid
    mac_host_id
    bluetooth_identity
    optional_usb_identity
  roles:
    audio_input
    session_peer
    remote_mic_receiver
    usb_peer
  transports:
    ble_gatt_bootstrap
    ble_l2cap_coc_session
    classic_a2dp_avrcp_audio
    usb_ncm_uac_when_available
  policy:
    session_enabled
    audio_selected
    remote_mic_allowed
    background_allowed
}
```

Pairing must not assume that enabling session means selecting Mac as audio
input. Those are separate user/product decisions.

## Protocol shape for Claude server

Claude should build the macOS server/helper against this contract:

- Swift helper preferred for native CoreBluetooth and stream handling.
- BLE GATT bootstrap discovers capabilities and current dynamic PSM.
- Main stream uses BLE L2CAP CoC.
- Binary framed stream, not JSON polling in the hot path.
- USB can later expose the same logical protocol over NCM or another transport.

Suggested frame header:

```text
magic:   4 bytes  "CTSP"
version: 1 byte
type:    1 byte
flags:   2 bytes
seq:     4 bytes
len:     4 bytes
payload: len bytes
```

Initial frame types:

- `hello`
- `capabilities`
- `status`
- `route_state`
- `command`
- `audio_pcm16`
- `telemetry`
- `error`

`audio_pcm16` should be on-demand. Do not stream the microphone constantly just
because session is connected.

## Remote mic recommendation

Primary path: ALSA/PDM capture on Car Thing -> PCM 16 kHz mono -> BLE L2CAP CoC
frames -> macOS helper -> STT/assistant pipeline.

Why:

- QN19 exposes PDM microphone capture via ALSA.
- Existing notes indicate no clean BT PCM/I2S line from Bluetooth chip to SoC
  codec path.
- HFP would require a SCO/eSCO path and a profile stack that is not the current
  product baseline.
- 16 kHz / 16-bit / mono PCM is about 256 kbit/s and fits the intended BLE CoC
  proof target.

HFP remains a separate experiment only if we specifically need a system-visible
Bluetooth microphone device on macOS.

## Resource policy

Play Now must remain quiet by default:

- keep iPhone/source stickiness as the top guardrail;
- do not run trusted output loops;
- do not scan trusted speakers in background;
- do not connect Mac session unless `client_enabled=true`;
- do not stream remote mic unless explicitly active.

Коммутатор may do one bounded scan/snapshot when entering the mode, then hold
only the selected/snapshot devices according to current route policy.

## GUI requirements

The route screen should show separate state lines:

```text
MODE: Play Now / Коммутатор
INPUT: iPhone / Mac / USB / none
SESSION: Mac off / idle / connected / streaming mic / error
OUTPUT: local / Fosi / line-out / none
```

In Play Now, external outputs should be visually inactive/greyed unless the user
explicitly enters Коммутатор. Mac session state must not be visually confused
with Mac audio route state.

## Handoff instructions for Claude

Do:

- implement the device-side role model first;
- treat Mac as multi-role endpoint;
- use BLE GATT for bootstrap and BLE L2CAP CoC for the main session stream;
- keep audio route and session route separate;
- make client ON/OFF affect only session/client behavior;
- preserve iPhone stickiness and Play Now quietness.

Do not:

- create a separate macOS mode;
- use the old document's "radio entirely dedicated to Mac" assumption;
- tie Mac audio input to client ON/OFF;
- use HFP as the first implementation path;
- introduce constant background scans/polls for trusted outputs or Mac services;
- use BlueZ/bluetoothd/bluetoothctl/sdptool workflows.

## Implementation order

1. Add/confirm endpoint registry roles: `audio_input`, `audio_output`,
   `session_peer`, `remote_mic_receiver`, `usb_peer`.
2. Add `RouteGraph` fields for active audio input, active output sink and
   active session sources.
3. Add GUI status separation: mode, input, session, output.
4. Add BLE GATT bootstrap spec and dynamic PSM publication.
5. Spike BLE L2CAP CoC echo/throughput between QN19 and Swift helper.
6. Add framed protocol.
7. Add remote mic PCM16 proof on demand.
8. Only after live proof, add macOS server features on top.

## Sources

Local project sources:

- [`docs/SESSION-OVER-TRANSPORTS-PLAN-2026-06-18.md`](SESSION-OVER-TRANSPORTS-PLAN-2026-06-18.md)
  — historical note, superseded only in the "separate macOS mode" premise.
- [`docs/FULL-HARDWARE-DRIVER-AUDIT-2026-06-18.md`](FULL-HARDWARE-DRIVER-AUDIT-2026-06-18.md)
  — live hardware/driver capability audit.
- [`ДРАЙВЕРЫ-ЯДРА-И-ЖЕЛЕЗО.md`](../ДРАЙВЕРЫ-ЯДРА-И-ЖЕЛЕЗО.md)
  — driver and hardware map.
- [`ТЕСТЫ-ЖЕЛЕЗА-MAX20332-И-USB-АУДИО.md`](../ТЕСТЫ-ЖЕЛЕЗА-MAX20332-И-USB-АУДИО.md)
  — USB audio/storage/MAX20332 prior proof.
- [`РЕЕСТР-РЕАЛИЗОВАННЫХ-ФУНКЦИЙ.md`](../РЕЕСТР-РЕАЛИЗОВАННЫХ-ФУНКЦИЙ.md)
  — implemented feature registry.

External primary/reference sources:

- Apple CoreBluetooth `CBL2CAPChannel`:
  <https://developer.apple.com/documentation/corebluetooth/cbl2capchannel>
- Apple `CBPeripheral.openL2CAPChannel(_:)`:
  <https://developer.apple.com/documentation/corebluetooth/cbperipheral/openl2capchannel%28_%3A%29>
- Apple `CBPeripheralManager.publishL2CAPChannel(withEncryption:)`:
  <https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager/publishl2capchannel%28withencryption%3A%29>
- Apple IOBluetooth framework:
  <https://developer.apple.com/documentation/iobluetooth>
- Apple macOS Bluetooth input/output user flow:
  <https://support.apple.com/guide/mac-help/connect-a-wireless-accessory-blth1004/mac>
- Apple `allowBluetoothHFP`:
  <https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/allowbluetoothhfp>
- Apple `allowBluetoothA2DP`:
  <https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/allowbluetootha2dp>
