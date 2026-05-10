#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("CARTHING_CONTROL_HOST", "0.0.0.0")
PORT = int(os.environ.get("CARTHING_CONTROL_PORT", "8099"))
STATE_DIR = Path(os.environ.get("CARTHING_CONTROL_STATE_DIR", "/tmp/carthing-control-server"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def device_dir(kind: str, device: str) -> Path:
    return ensure_dir(STATE_DIR / kind / device)


def safe_device(params):
    device = params.get("device", ["device1"])[0].strip()
    return device or "device1"


def list_pending(device: str):
    root = device_dir("pending", device)
    return sorted(root.glob("*.json"))


def list_running(device: str):
    root = device_dir("running", device)
    return sorted(root.glob("*.json"))


def list_completed(device: str):
    root = device_dir("completed", device)
    return sorted(root.glob("*.json"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def next_command(device: str):
    pending = list_pending(device)
    if not pending:
        return None
    source = pending[0]
    payload = read_json(source)
    payload["dispatched_at"] = now_iso()
    dest = device_dir("running", device) / source.name
    source.rename(dest)
    write_json(dest, payload)
    return payload


def append_log(name: str, line: str):
    ensure_dir(STATE_DIR)
    with open(STATE_DIR / name, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "CarThingReverseControl/1.0"

    def send_json(self, code, payload):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        device = safe_device(params)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if parsed.path == "/agent/poll":
            command = next_command(device)
            append_log(
                "poll.log",
                f"{stamp} device={device} command={command['id'] if command else '-'}",
            )
            if command:
                payload = {"ok": True, "command": {"id": command["id"], "shell": command["shell"]}}
            else:
                payload = {"ok": True, "command": None}
            self.send_json(200, payload)
            return

        if parsed.path == "/agent/status":
            payload = {
                "ok": True,
                "device": device,
                "pending": [p.stem for p in list_pending(device)],
                "running": [p.stem for p in list_running(device)],
                "completed": [p.stem for p in list_completed(device)],
            }
            self.send_json(200, payload)
            return

        line = f"{stamp} path={parsed.path} device={device} params={params}"
        append_log("beacon.log", line)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        self.send_json(200, {"ok": True})

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        device = safe_device(params)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if parsed.path == "/agent/result":
            body = self.read_json_body()
            command_id = body.get("command_id") or params.get("id", ["unknown"])[0]
            running = device_dir("running", device) / f"{command_id}.json"
            completed = device_dir("completed", device) / f"{command_id}.json"
            payload = {
                "received_at": now_iso(),
                "device": device,
                "result": body,
            }
            if running.exists():
                try:
                    original = read_json(running)
                    payload["command"] = original
                    running.unlink()
                except Exception:
                    pass
            write_json(completed, payload)
            append_log(
                "results.log",
                f"{stamp} device={device} command={command_id} exit={body.get('exit_code')}",
            )
            self.send_json(200, {"ok": True, "stored": str(completed)})
            return

        self.send_json(404, {"ok": False, "error": "unknown endpoint"})

    def log_message(self, fmt, *args):
        return


def main():
    for sub in ("pending", "running", "completed"):
        ensure_dir(STATE_DIR / sub)
    server = HTTPServer((HOST, PORT), Handler)
    print(f"reverse control server listening on {HOST}:{PORT}", flush=True)
    print(f"state dir: {STATE_DIR}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
