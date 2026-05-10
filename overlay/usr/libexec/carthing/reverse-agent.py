#!/usr/bin/env python3
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CONFIG_PATH = "/etc/default/carthing"
STATE_DIR = Path("/run/carthing")
RESULT_PATH = STATE_DIR / "reverse-agent-pending-result.json"
STATE_PATH = STATE_DIR / "reverse-agent.state"


def load_config():
    config = {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key] = value.strip().strip('"')
    return config


CONFIG = load_config()
BASE_URL = CONFIG.get("CARTHING_REVERSE_AGENT_URL", "http://172.16.42.1:8099").rstrip("/")
DEVICE_ID = CONFIG.get("CARTHING_REVERSE_AGENT_DEVICE_ID", "device1")
POLL_INTERVAL = max(1, int(CONFIG.get("CARTHING_REVERSE_AGENT_POLL_INTERVAL", "2")))
COMMAND_TIMEOUT = max(1, int(CONFIG.get("CARTHING_REVERSE_AGENT_COMMAND_TIMEOUT", "45")))
MAX_OUTPUT = max(1024, int(CONFIG.get("CARTHING_REVERSE_AGENT_MAX_OUTPUT", "65536")))


def write_state(message):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(message + "\n", encoding="utf-8")


def beacon(*args):
    try:
        subprocess.run(
            ["/usr/libexec/carthing/beacon", *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def http_get_json(path, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{BASE_URL}{path}?{query}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def http_post_json(path, params, payload):
    query = urllib.parse.urlencode(params)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}?{query}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def trim_text(value):
    if len(value) <= MAX_OUTPUT:
        return value
    keep = MAX_OUTPUT // 2
    return value[:keep] + "\n...[truncated]...\n" + value[-keep:]


def run_command(command_id, shell_command):
    started = time.time()
    completed = {
        "device_id": DEVICE_ID,
        "command_id": command_id,
        "command": shell_command,
        "started_at": started,
    }
    beacon("reverse-command-start", command_id)
    write_state(f"running {command_id}")
    try:
        result = subprocess.run(
            ["/bin/sh", "-c", shell_command],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
        completed["exit_code"] = result.returncode
        completed["stdout"] = trim_text(result.stdout)
        completed["stderr"] = trim_text(result.stderr)
        completed["timed_out"] = False
    except subprocess.TimeoutExpired as exc:
        completed["exit_code"] = 124
        completed["stdout"] = trim_text(exc.stdout or "")
        completed["stderr"] = trim_text((exc.stderr or "") + "\ncommand timed out")
        completed["timed_out"] = True
    completed["finished_at"] = time.time()
    RESULT_PATH.write_text(json.dumps(completed), encoding="utf-8")
    write_state(f"completed {command_id}")
    beacon("reverse-command-done", command_id)


def flush_result():
    if not RESULT_PATH.exists():
        return True
    try:
        payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        response = http_post_json(
            "/agent/result",
            {"device": DEVICE_ID, "id": payload["command_id"]},
            payload,
        )
        if response.get("ok"):
            RESULT_PATH.unlink(missing_ok=True)
            write_state(f"idle acked {payload['command_id']}")
            beacon("reverse-result-acked", payload["command_id"])
            return True
    except Exception as exc:
        write_state(f"result-post-failed {exc}")
    return False


def poll_once():
    try:
        response = http_get_json(
            "/agent/poll",
            {"device": DEVICE_ID},
        )
        command = response.get("command")
        if not command:
            write_state("idle")
            return
        run_command(command["id"], command["shell"])
    except urllib.error.URLError as exc:
        write_state(f"poll-failed {exc}")
    except Exception as exc:
        write_state(f"poll-error {exc}")


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_state("starting")
    beacon("reverse-agent-entry", DEVICE_ID)
    while True:
        flushed = flush_result()
        if flushed:
            poll_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
