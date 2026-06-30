#!/usr/bin/env python3
import json
import sys
import time


PLUGIN_ID = "dev.carthing.example.button-deck"
revision = 0
presses = 0
mode = "READY"


def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def publish():
    global revision
    revision += 1
    send(
        {
            "type": "snapshot",
            "snapshot": {
                "schema": 1,
                "plugin_id": PLUGIN_ID,
                "revision": revision,
                "cards": [
                    {
                        "id": "deck",
                        "title": "Button Deck",
                        "subtitle": "External .ctplugin example",
                        "status": mode,
                        "accent": "#33FF88",
                        "rows": [
                            {
                                "id": "presses",
                                "label": "PRESSES",
                                "value": str(presses),
                            },
                            {
                                "id": "updated",
                                "label": "UPDATED",
                                "value": time.strftime("%H:%M:%S"),
                            },
                        ],
                        "actions": [
                            {
                                "id": "run",
                                "label": "RUN",
                                "style": "primary",
                                "enabled": True,
                            },
                            {
                                "id": "reset",
                                "label": "RESET",
                                "style": "normal",
                                "enabled": True,
                            },
                        ],
                    }
                ],
            },
        }
    )


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    message_type = message.get("type")
    if message_type == "start":
        publish()
    elif message_type == "action":
        action_id = (message.get("action") or {}).get("action_id")
        if action_id == "run":
            presses += 1
            mode = "ACTIVE"
        elif action_id == "reset":
            presses = 0
            mode = "READY"
        publish()
    elif message_type == "stop":
        break
