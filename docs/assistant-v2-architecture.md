# Assistant v2 architecture

Assistant v2 keeps Play Now and voice transport as separate product planes.

## State ownership

- `Assistant view`: opening it never starts capture. The microphone starts only
  from its explicit button, and leaving the view always stops capture.
- `CTSP session`: Mac-owned BLE L2CAP CoC link. It remains available for sparse
  HomePod metadata while capture is off. GATT `client_toggle` may open or close
  the session, but cannot enable microphone capture.
- `Microphone capture`: device-owned view toggle. When off, ALSA and the PDM
  capture path close while the metadata link remains idle.

## Data path

`PDM 48 kHz/4ch -> HCIC gain -> SpeexDSP -> Opus VOIP 16 kHz mono -> BLE L2CAP CoC -> localhost TCP -> streaming Whisper -> final transcript -> assistant`

When iOS controls remote HomePod playback, AMS exposes only the paused local
iPhone session. The Mac therefore reads the active HomePod AirPlay 2/MRP
session, groups stereo peers, and sends structured Now Playing snapshots over
the same idle CTSP link. Local iPhone playback continues to use AMS directly.
Remote playback controls use the bonded iPhone HID consumer-control channel.

Audio reception, VAD, partial Whisper, final Whisper, and LLM response run independently. A slow STT or LLM request cannot stop or drain the Bluetooth audio reader.

Continuous speech is committed in 14-second Whisper windows with a two-second
overlap. The confirmed prefix and current partial tail are stitched before they
reach the GUI; only endpoint silence starts the LLM.

The GUI is dirty-driven. Hidden Assistant text cannot invalidate Play Now, and
the Assistant screen lays out only the lines that can actually be displayed.

## Transport decision

CoreBluetooth L2CAP CoC remains the primary transport:

- it is a public macOS API with stream I/O;
- LE credit-based flow control already provides segmentation and reassembly;
- the measured Opus payload is far below the available CoC bandwidth;
- RFCOMM would require a second Classic identity, SDP profile, and pairing flow without removing the single-controller scheduling constraint.

CoreBluetooth owns the macOS connection interval. Opus uses 60 ms frames to
reduce CoC SDU pressure by one third while staying far below Whisper latency.
Bootstrap advertising uses `20 ms`; bonded sticky iPhone advertising uses
`152.5 ms`.
