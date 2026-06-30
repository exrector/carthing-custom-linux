#!/usr/bin/env python3
"""Continuously capture Car Thing device, CTSP, and assistant soak telemetry."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


DEFAULT_LOG_DIR = Path.home() / "Library/Logs/CarThing"
DEFAULT_OUTPUT = DEFAULT_LOG_DIR / "soak.jsonl"
DEFAULT_CURSOR = DEFAULT_LOG_DIR / "soak-cursors.json"
DEVICE_JOURNAL = "/run/carthing-state/carthing/connection-events.jsonl"
LOCAL_LOGS = {
    "btlink": Path("/private/tmp/carthing-btlink.err"),
    "assistant": Path("/private/tmp/carthing-btwhisper.err"),
}


def run(args, timeout=8):
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except Exception as error:
        return -1, "", str(error)


class Monitor:
    def __init__(self, output, cursor_path, host, interval):
        self.output = Path(output).expanduser()
        self.cursor_path = Path(cursor_path).expanduser()
        self.host = host
        self.interval = max(2.0, float(interval))
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.cursors = self._load_cursors()

    def _load_cursors(self):
        try:
            data = json.loads(self.cursor_path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cursors(self):
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cursor_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.cursors, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.cursor_path)

    def append(self, kind, **fields):
        record = {
            "schema": 1,
            "captured_at": time.time(),
            "kind": kind,
            **fields,
        }
        with self.output.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            )
            handle.flush()

    def capture_local_log(self, source, path):
        key = f"local:{source}"
        try:
            stat = path.stat()
        except FileNotFoundError:
            return
        cursor = self.cursors.get(key)
        identity = f"{stat.st_dev}:{stat.st_ino}"
        if not isinstance(cursor, dict) or cursor.get("identity") != identity:
            self.cursors[key] = {
                "identity": identity,
                "offset": stat.st_size,
            }
            self.append(
                "log_cursor_started",
                source=source,
                path=str(path),
                offset=stat.st_size,
            )
            return
        offset = int(cursor.get("offset", 0))
        if stat.st_size < offset:
            offset = 0
        if stat.st_size == offset:
            return
        with path.open("rb") as handle:
            handle.seek(offset)
            payload = handle.read()
            cursor["offset"] = handle.tell()
        for raw_line in payload.splitlines():
            line = raw_line.decode("utf-8", "replace")
            self.append("source_log", source=source, line=line)

    def _ssh(self, command, timeout=8):
        return run(
            [
                "/usr/bin/ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=4",
                self.host,
                command,
            ],
            timeout=timeout,
        )

    def capture_device(self):
        command = r"""
printf 'runtime='; cat /run/carthing/runtime-bt.json 2>/dev/null || true
printf '\nuptime='; cut -d' ' -f1 /proc/uptime 2>/dev/null || true
printf '\nloadavg='; cat /proc/loadavg 2>/dev/null || true
printf '\nmem_available_kb='; awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null
printf '\ntemperature_mc='; cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || true
pid="$(ps | grep carthing_runtime.py | grep -v grep | awk 'NR == 1 {print $1}')"
printf '\nruntime_count='; ps | grep carthing_runtime.py | grep -v grep | wc -l
printf '\nruntime_rss_kb='; [ -n "$pid" ] && awk '/VmRSS:/ {print $2}' "/proc/$pid/status" || true
printf '\nroot_mount='; mount | grep ' on / ' | head -1
printf '\nruntime_log_size='; wc -c < /var/run/carthing/carthing-remote.log 2>/dev/null || echo 0
printf '\n'
"""
        code, stdout, stderr = self._ssh(command)
        if code != 0:
            self.append(
                "device_snapshot",
                ok=False,
                returncode=code,
                error=stderr.strip(),
            )
            return
        values = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value.strip()
        runtime = None
        try:
            runtime = json.loads(values.pop("runtime", "") or "null")
        except ValueError as error:
            values["runtime_parse_error"] = str(error)
        self.append("device_snapshot", ok=True, runtime=runtime, **values)

    def capture_device_journal(self):
        key = "remote:connection_journal"
        size_code, size_out, size_err = self._ssh(
            f"wc -c < {DEVICE_JOURNAL} 2>/dev/null || echo 0"
        )
        if size_code != 0:
            self.append(
                "journal_read_error",
                error=size_err.strip(),
                returncode=size_code,
            )
            return
        try:
            size = int(size_out.strip() or 0)
        except ValueError:
            return
        offset = int(self.cursors.get(key, 0) or 0)
        if size < offset:
            offset = 0
        if size == offset:
            return
        code, stdout, stderr = self._ssh(
            f"tail -c +{offset + 1} {DEVICE_JOURNAL} 2>/dev/null",
            timeout=12,
        )
        if code != 0:
            self.append(
                "journal_read_error",
                error=stderr.strip(),
                returncode=code,
            )
            return
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                self.append("connection_journal_malformed", line=line)
                continue
            self.append("connection_event", event=event)
        self.cursors[key] = size

    def capture_mac(self):
        processes = []
        code, stdout, _ = run(
            ["/bin/ps", "-axo", "pid=,pcpu=,rss=,etime=,command="]
        )
        if code == 0:
            for line in stdout.splitlines():
                if (
                    "CarThingBTLink.app/Contents/MacOS/CarThingBTLink" in line
                    or "voice-assistant/bt_assistant_v2.py" in line
                ):
                    processes.append(line.strip())
        thermal_code, thermal, _ = run(["/usr/bin/pmset", "-g", "therm"])
        self.append(
            "mac_snapshot",
            loadavg=list(os.getloadavg()),
            processes=processes,
            thermal=thermal.strip() if thermal_code == 0 else "",
        )

    def capture_once(self):
        for source, path in LOCAL_LOGS.items():
            self.capture_local_log(source, path)
        self.capture_device()
        self.capture_mac()
        self.capture_device_journal()
        self._save_cursors()

    def run_forever(self):
        self.append(
            "monitor_started",
            pid=os.getpid(),
            host=self.host,
            interval_s=self.interval,
        )
        next_device = 0.0
        next_mac = 0.0
        next_journal = 0.0
        while True:
            now = time.monotonic()
            for source, path in LOCAL_LOGS.items():
                self.capture_local_log(source, path)
            if now >= next_device:
                self.capture_device()
                next_device = now + self.interval
            if now >= next_mac:
                self.capture_mac()
                next_mac = now + max(30.0, self.interval)
            if now >= next_journal:
                self.capture_device_journal()
                next_journal = now + 30.0
            self._save_cursors()
            time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--cursor", default=str(DEFAULT_CURSOR))
    parser.add_argument(
        "--host",
        default=os.environ.get("CARTHING_SSH_HOST", "carthing"),
    )
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    monitor = Monitor(args.output, args.cursor, args.host, args.interval)
    if args.once:
        monitor.capture_once()
    else:
        monitor.run_forever()


if __name__ == "__main__":
    main()
