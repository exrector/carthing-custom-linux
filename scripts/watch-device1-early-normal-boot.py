#!/usr/bin/env python3

import argparse
import subprocess
import sys
import time
from datetime import datetime


TRIGGERS = [
    "172.16.42.77",
    "172.16.42.78",
    "172.16.42.84",
    "172.16.42.211",
    "172.16.42.217",
]

MARKERS = [
    "172.16.42.77",
    "172.16.42.78",
    "172.16.42.79",
    "172.16.42.84",
    "172.16.42.85",
    "172.16.42.176",
    "172.16.42.177",
    "172.16.42.178",
    "172.16.42.179",
    "172.16.42.185",
    "172.16.42.186",
    "172.16.42.187",
    "172.16.42.188",
    "172.16.42.189",
    "172.16.42.190",
    "172.16.42.191",
    "172.16.42.192",
    "172.16.42.193",
    "172.16.42.194",
    "172.16.42.195",
    "172.16.42.196",
    "172.16.42.197",
    "172.16.42.198",
    "172.16.42.200",
    "172.16.42.201",
    "172.16.42.202",
    "172.16.42.203",
    "172.16.42.204",
    "172.16.42.205",
    "172.16.42.206",
    "172.16.42.207",
    "172.16.42.208",
    "172.16.42.210",
    "172.16.42.211",
    "172.16.42.212",
    "172.16.42.213",
    "172.16.42.214",
    "172.16.42.215",
    "172.16.42.216",
    "172.16.42.217",
    "172.16.42.218",
    "172.16.42.219",
]


def run(cmd: str):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True)


def ping_parallel(ips, timeout_ms=200):
    procs = {
        ip: subprocess.Popen(
            ["ping", "-c", "1", "-W", str(timeout_ms), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for ip in ips
    }
    states = {}
    for ip, proc in procs.items():
        states[ip] = "ok" if proc.wait() == 0 else "fail"
    return states


def print_section(title, text):
    print(title)
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        print()


def snapshot(label):
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"=== snapshot {label} {now} ===", flush=True)

    # Keep the first frame cheap: host bring-up plus parallel marker sweep.
    bring = run("./scripts/bring-up-device1-normal-boot-macos.sh")
    print_section(f"--- bring-up rc={bring.returncode} ---", bring.stdout + bring.stderr)

    markers = ping_parallel(MARKERS)
    print("--- markers ---")
    for ip in MARKERS:
        print(f"{ip} {markers[ip]}")

    check = run("./scripts/check-device1-normal-boot-macos.sh")
    print_section(f"--- check rc={check.returncode} ---", check.stdout + check.stderr)

    ports = run(
        "for p in 22 8080 2323; do "
        "nc -G 1 -z 172.16.42.77 $p >/dev/null 2>&1 && echo 172.16.42.77:$p open || "
        "echo 172.16.42.77:$p closed; "
        "done"
    )
    print_section(f"--- ports rc={ports.returncode} ---", ports.stdout + ports.stderr)

    queue = run("curl -fsS 'http://127.0.0.1:8099/agent/status?device=device1' || true")
    print_section(f"--- queue rc={queue.returncode} ---", queue.stdout + queue.stderr)
    print(flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll", type=float, default=0.4)
    parser.add_argument("--post-delays", default="2,8")
    args = parser.parse_args()

    delays = []
    for item in args.post_delays.split(","):
        item = item.strip()
        if item:
            delays.append(float(item))

    print("watcher: armed", flush=True)
    start = time.monotonic()

    while time.monotonic() - start < args.timeout:
        run("./scripts/bring-up-device1-normal-boot-macos.sh >/dev/null 2>&1 || true")
        seen = [ip for ip, state in ping_parallel(TRIGGERS).items() if state == "ok"]
        if seen:
            trigger_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"watcher: trigger {trigger_at} seen={' '.join(seen)}", flush=True)
            snapshot("t0")
            last = 0.0
            for delay in delays:
                sleep_for = max(0.0, delay - last)
                if sleep_for:
                    time.sleep(sleep_for)
                snapshot(f"t+{int(delay)}s")
                last = delay
            return 0
        time.sleep(args.poll)

    print("watcher: timeout", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
