#!/usr/bin/env python3
"""Single-action macOS shortcut display plugin."""

import json
import subprocess
import sys
import time
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((PACKAGE_ROOT / "shortcut.json").read_text())
PLUGIN_ID = str(CONFIG["plugin_id"])
ACTION_ID = str(CONFIG["action_id"])
LABEL = str(CONFIG["label"])
COMMAND = [str(value) for value in CONFIG["command"]]
revision = 0
status = "READY"


def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def publish():
    global revision
    revision += 1
    send({
        "type": "snapshot",
        "snapshot": {
            "schema": 1,
            "plugin_id": PLUGIN_ID,
            "revision": revision,
            "cards": [{
                "id": "shortcut",
                "title": LABEL,
                "subtitle": "",
                "status": status,
                "accent": "#33FF88",
                "rows": [],
                "actions": [{
                    "id": ACTION_ID,
                    "label": LABEL,
                    "style": "normal",
                    "enabled": True,
                }],
            }],
        },
    })


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
        if action_id == ACTION_ID:
            try:
                subprocess.Popen(
                    COMMAND,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                status = time.strftime("%H:%M")
            except Exception:
                status = "ERROR"
            publish()
    elif message_type == "stop":
        break
