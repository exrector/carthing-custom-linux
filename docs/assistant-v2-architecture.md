# Assistant v2 architecture

Assistant v2 keeps Play Now and voice transport as separate product planes.

## State ownership

- `Assistant view`: presentation only. Opening or closing it never changes Bluetooth or ALSA.
- `CTSP session`: Mac-owned BLE L2CAP CoC link. GATT `client_toggle` may open or close the session, but cannot enable microphone capture.
- `Microphone capture`: device-owned persistent toggle. When off, ALSA closes and the Mac session disconnects. When on, the device opens one bounded bootstrap window and reconnects automatically with backoff.

## Data path

`PDM 48 kHz/4ch -> HCIC gain -> SpeexDSP -> Opus VOIP 16 kHz mono -> BLE L2CAP CoC -> localhost TCP -> streaming Whisper -> final transcript -> assistant`

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

Connection parameters follow Apple's accessory guidance: `15-30 ms`, zero peripheral latency, and a six-second supervision timeout. Bootstrap advertising uses `20 ms`; bonded sticky iPhone advertising uses `152.5 ms`.
