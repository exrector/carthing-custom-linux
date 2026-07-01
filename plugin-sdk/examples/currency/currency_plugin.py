#!/usr/bin/env python3
import json
import os
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


PLUGIN_ID = "dev.carthing.example.currency"
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CARTHING_PLUGIN_DATA_DIR", ROOT))
CACHE_PATH = DATA_DIR / "currency-cache.json"
stop_event = threading.Event()
write_lock = threading.Lock()
revision = 0


def read_cache():
    try:
        value = json.loads(CACHE_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def send(message):
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    with write_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def publish(state):
    global revision
    revision += 1
    send({
        "type": "snapshot",
        "snapshot": {
            "schema": 1,
            "plugin_id": PLUGIN_ID,
            "revision": revision,
            "cards": [{
                "id": "rates",
                "title": "КУРС ЦБ",
                "subtitle": "рублей за единицу",
                "status": state.get("date") or "ожидание",
                "accent": "#FFAA00",
                "rows": [
                    {
                        "id": "usd",
                        "label": "USD",
                        "value": state.get("USD") or "--",
                    },
                    {
                        "id": "eur",
                        "label": "EUR",
                        "value": state.get("EUR") or "--",
                    },
                ],
                "actions": [],
            }],
        },
    })


def fetch():
    request = urllib.request.Request(
        "https://www.cbr.ru/scripts/XML_daily.asp",
        headers={"User-Agent": "CarThingCurrency/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        root = ET.fromstring(response.read())
    state = {"date": root.attrib.get("Date") or time.strftime("%d.%m.%Y")}
    for item in root.findall("Valute"):
        code = item.findtext("CharCode")
        if code not in ("USD", "EUR"):
            continue
        rate = item.findtext("VunitRate") or item.findtext("Value") or ""
        state[code] = f"{float(rate.replace(',', '.')):.2f}"
    if not all(state.get(code) for code in ("USD", "EUR")):
        raise ValueError("USD/EUR are missing in the CBR response")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(state, ensure_ascii=False))
    return state


def updater():
    publish(read_cache())
    while not stop_event.is_set():
        try:
            publish(fetch())
        except Exception as error:
            print(f"currency update failed: {error}", file=sys.stderr, flush=True)
        if stop_event.wait(3600):
            break


thread = None
for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    if message.get("type") == "start" and thread is None:
        thread = threading.Thread(target=updater, daemon=True)
        thread.start()
    elif message.get("type") == "stop":
        stop_event.set()
        break
