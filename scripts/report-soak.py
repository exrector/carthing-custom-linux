#!/usr/bin/env python3
"""Summarize append-only Car Thing soak telemetry."""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import time
from pathlib import Path


METRIC_PATTERNS = {
    "ctsp_rtt_ms": re.compile(r"\bctsp_probe\b.*\brtt_ms=([0-9.]+)"),
    "capture_to_mac_ms": re.compile(r"\bcapture_to_mac_ms=([0-9.]+)"),
    "bluetooth_ms": re.compile(r"\bbluetooth_ms=([0-9.]+)"),
    "reconnect_l2cap_ms": re.compile(r"\breconnect_l2cap_ms=([0-9.]+)"),
}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def describe(values):
    if not values:
        return "n=0"
    return (
        f"n={len(values)} min={min(values):.1f} "
        f"p50={statistics.median(values):.1f} "
        f"p95={percentile(values, 0.95):.1f} max={max(values):.1f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "journal",
        nargs="?",
        type=Path,
        default=Path.home() / "Library/Logs/CarThing/soak.jsonl",
    )
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()
    cutoff = time.time() - max(0.0, args.hours) * 3600.0

    kinds = collections.Counter()
    source_lines = collections.Counter()
    connection_events = collections.Counter()
    metrics = collections.defaultdict(list)
    assistant_events = collections.Counter()
    stt_ms = []
    llm_ms = []
    snapshots = 0
    iphone_connected = 0
    malformed = 0
    monitor_started_at = None

    with args.journal.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            kind = record.get("kind", "unknown")
            if kind == "monitor_started" and monitor_started_at is None:
                monitor_started_at = float(record.get("captured_at") or cutoff)
            event_time = float(record.get("captured_at") or 0.0)
            if kind == "connection_event":
                event_time = float(
                    (record.get("event") or {}).get("ts") or event_time
                )
            effective_cutoff = max(cutoff, monitor_started_at or cutoff)
            if event_time < effective_cutoff:
                continue
            kinds[kind] += 1
            if kind == "connection_event":
                event = record.get("event") or {}
                connection_events[str(event.get("event", "unknown"))] += 1
            elif kind == "device_snapshot" and record.get("ok"):
                snapshots += 1
                runtime = record.get("runtime") or {}
                bt = runtime.get("bt") or {}
                iphone_connected += int(bool(bt.get("connected")))
            elif kind == "source_log":
                source = str(record.get("source", "unknown"))
                source_lines[source] += 1
                text = str(record.get("line", ""))
                for name, pattern in METRIC_PATTERNS.items():
                    match = pattern.search(text)
                    if match:
                        metrics[name].append(float(match.group(1)))
                if text.startswith("[bt-assistant-v2] "):
                    try:
                        payload = json.loads(text.split(" ", 1)[1])
                    except ValueError:
                        continue
                    event = str(payload.get("event", "unknown"))
                    assistant_events[event] += 1
                    if event == "stt_result" and payload.get("stt_ms") is not None:
                        stt_ms.append(float(payload["stt_ms"]))
                    if event == "llm_result" and payload.get("llm_ms") is not None:
                        llm_ms.append(float(payload["llm_ms"]))

    print(
        f"window_hours={max(0.0, args.hours):g} "
        f"records={sum(kinds.values())} malformed={malformed}"
    )
    if snapshots:
        print(
            f"iphone_connected={iphone_connected}/{snapshots} "
            f"({iphone_connected / snapshots * 100:.1f}%)"
        )
    print("connection_events:")
    for name, count in sorted(connection_events.items()):
        print(f"  {name}: {count}")
    print("transport:")
    for name in METRIC_PATTERNS:
        print(f"  {name}: {describe(metrics[name])}")
    print(f"assistant_stt_ms: {describe(stt_ms)}")
    print(f"assistant_llm_ms: {describe(llm_ms)}")
    print("assistant_events:")
    for name, count in sorted(assistant_events.items()):
        print(f"  {name}: {count}")
    print("captured_source_lines:")
    for name, count in sorted(source_lines.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
