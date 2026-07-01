#!/usr/bin/env python3
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


PLUGIN_ID = "dev.carthing.example.weather"
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = Path(os.environ.get("CARTHING_PLUGIN_DATA_DIR", ROOT))
CACHE_PATH = DATA_DIR / "weather-cache.json"
stop_event = threading.Event()
write_lock = threading.Lock()
revision = 0


WEATHER_CODES = {
    0: "Ясно",
    1: "Преим. ясно",
    2: "Перем. облачно",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Морось",
    53: "Морось",
    55: "Сильная морось",
    61: "Дождь",
    63: "Дождь",
    65: "Сильный дождь",
    71: "Снег",
    73: "Снег",
    75: "Сильный снег",
    80: "Ливень",
    81: "Ливень",
    82: "Сильный ливень",
    95: "Гроза",
    96: "Гроза с градом",
    99: "Гроза с градом",
}


def read_json(path, fallback):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else fallback
    except Exception:
        return fallback


def send(message):
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    with write_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def publish(state):
    global revision
    revision += 1
    temperature = state.get("temperature")
    apparent = state.get("apparent")
    condition = state.get("condition") or "Нет данных"
    send({
        "type": "snapshot",
        "snapshot": {
            "schema": 1,
            "plugin_id": PLUGIN_ID,
            "revision": revision,
            "cards": [{
                "id": "weather",
                "title": state.get("city") or "Погода",
                "subtitle": "Open-Meteo",
                "status": state.get("updated") or "ожидание",
                "accent": "#66CCFF",
                "rows": [
                    {
                        "id": "temperature",
                        "label": "СЕЙЧАС",
                        "value": (
                            f"{round(float(temperature))}°"
                            if temperature is not None
                            else "--°"
                        ),
                    },
                    {
                        "id": "condition",
                        "label": "",
                        "value": (
                            f"{condition} · {round(float(apparent))}°"
                            if apparent is not None
                            else condition
                        ),
                    },
                ],
                "actions": [],
            }],
        },
    })


def fetch(config):
    query = urllib.parse.urlencode({
        "latitude": config["latitude"],
        "longitude": config["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code",
        "timezone": config.get("timezone") or "auto",
    })
    request = urllib.request.Request(
        "https://api.open-meteo.com/v1/forecast?" + query,
        headers={"User-Agent": "CarThingWeather/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        body = json.load(response)
    current = body["current"]
    state = {
        "city": config.get("city") or "Погода",
        "temperature": current.get("temperature_2m"),
        "apparent": current.get("apparent_temperature"),
        "condition": WEATHER_CODES.get(
            int(current.get("weather_code", -1)),
            "Неизвестно",
        ),
        "updated": time.strftime("%H:%M"),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(state, ensure_ascii=False))
    return state


def updater():
    config = read_json(CONFIG_PATH, {
        "city": "Москва",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "timezone": "Europe/Moscow",
        "refresh_seconds": 900,
    })
    cached = read_json(CACHE_PATH, {"city": config.get("city") or "Погода"})
    publish(cached)
    refresh = max(300, int(config.get("refresh_seconds") or 900))
    while not stop_event.is_set():
        try:
            publish(fetch(config))
        except Exception as error:
            print(f"weather update failed: {error}", file=sys.stderr, flush=True)
        if stop_event.wait(refresh):
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
