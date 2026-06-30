#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PLUGIN_ID = "dev.carthing.example.mac-deck"
PACKAGE_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_ROOT / "actions.json"
revision = 0
last_action = "NONE"
status = "READY"


def load_actions():
    try:
        rows = json.loads(CONFIG_PATH.read_text())
    except Exception:
        rows = []
    actions = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        action_id = str(row.get("id") or "")[:80]
        label = str(row.get("label") or "")[:32]
        command = row.get("command")
        if action_id and label and isinstance(command, list) and command:
            actions.append(
                {
                    "id": action_id,
                    "label": label,
                    "command": [str(value) for value in command],
                }
            )
    return actions


actions = load_actions()


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
                        "title": "Mac Deck",
                        "subtitle": "Bluetooth desktop controls",
                        "status": status,
                        "accent": "#33FF88",
                        "rows": [
                            {
                                "id": "host",
                                "label": "MAC",
                                "value": os.uname().nodename.split(".")[0],
                            },
                            {
                                "id": "last",
                                "label": "LAST",
                                "value": last_action,
                            },
                        ],
                        "actions": [
                            {
                                "id": action["id"],
                                "label": action["label"],
                                "style": (
                                    "primary"
                                    if index == 0
                                    else "normal"
                                ),
                                "enabled": True,
                            }
                            for index, action in enumerate(actions)
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
        action = next(
            (item for item in actions if item["id"] == action_id),
            None,
        )
        if action is not None:
            try:
                subprocess.Popen(
                    action["command"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                last_action = action["label"]
                status = time.strftime("%H:%M")
            except Exception:
                last_action = action["label"]
                status = "ERROR"
        publish()
    elif message_type == "stop":
        break
