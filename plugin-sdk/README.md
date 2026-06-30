# Car Thing Display Plugin SDK

A display plugin is an independent `.ctplugin` ZIP archive. It is installed and
enabled in the CarThingBTLink macOS app. The app runs each enabled plugin as a
separate process and transports its UI model to the fixed fourth Car Thing view
over CTSP Bluetooth L2CAP CoC. USB is not part of the product path.

## Package

The archive root contains:

```text
manifest.json
executable
optional resources...
```

Minimal manifest:

```json
{
  "schema": 1,
  "id": "com.example.my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "executable": "plugin.py"
}
```

Build the included example:

```sh
chmod +x plugin-sdk/examples/button-deck/button_deck.py
./plugin-sdk/package-plugin.sh \
  plugin-sdk/examples/button-deck \
  build/ButtonDeck.ctplugin
```

Every new or updated archive is installed disabled. The user must enable it in
the macOS app. Archives must be trusted: version 1 runs executables as the
current user and does not provide an OS sandbox.

## JSONL protocol

The executable is launched with `--carthing-plugin-stdio`. stdin and stdout use
one JSON object per line. stdout must contain protocol messages only; diagnostics
belong on stderr. A line buffer over 256 KiB terminates the plugin.

Host start:

```json
{"type":"start","protocol":1}
```

Plugin snapshot:

```json
{"type":"snapshot","snapshot":{"schema":1,"plugin_id":"com.example.my-plugin","revision":1,"cards":[{"id":"main","title":"My Plugin","subtitle":"","status":"READY","accent":"#33FF88","rows":[{"id":"value","label":"VALUE","value":"42"}],"actions":[{"id":"run","label":"RUN","style":"primary","enabled":true}]}]}}
```

Host action:

```json
{"type":"action","action":{"schema":1,"plugin_id":"com.example.my-plugin","card_id":"main","action_id":"run"}}
```

Only actions that are enabled in the latest snapshot are forwarded. Snapshot
transport is coalesced to at most two updates per second per plugin. Limits:
8 cards, 8 rows and 4 actions per card, 48 KiB CTSP JSON payload. The device
currently renders the first card, up to six rows, and up to three actions.

The complete reference implementation is in
`plugin-sdk/examples/button-deck`.
