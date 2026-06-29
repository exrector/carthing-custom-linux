#!/usr/bin/env python3
"""Summarize the Car Thing append-only Bluetooth connection journal."""

import argparse
import collections
import json
from pathlib import Path


def load_events(path):
    events = []
    malformed = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                malformed += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                malformed += 1
    return events, malformed


def event_gap_ms(start, end):
    if start.get("boot_id") == end.get("boot_id"):
        return (
            float(end.get("monotonic_s", 0))
            - float(start.get("monotonic_s", 0))
        ) * 1000.0
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("journal", type=Path)
    args = parser.parse_args()

    events, malformed = load_events(args.journal)
    counts = collections.Counter(row.get("event", "unknown") for row in events)
    disconnects = [
        row for row in events if row.get("event") == "iphone_disconnected"
    ]

    print(f"events={len(events)} malformed={malformed}")
    for name, count in sorted(counts.items()):
        print(f"{name}: {count}")

    if not disconnects:
        print("iphone_flaps: 0")
        return

    print(f"iphone_flaps: {len(disconnects)}")
    for disconnected in disconnects:
        reconnect = next(
            (
                row
                for row in events
                if row.get("event") == "iphone_services_ready"
                and row.get("boot_id") == disconnected.get("boot_id")
                and float(row.get("monotonic_s", 0))
                > float(disconnected.get("monotonic_s", 0))
            ),
            None,
        )
        gap = event_gap_ms(disconnected, reconnect) if reconnect else None
        gap_text = f"{gap:.1f}ms" if gap is not None else "not recovered"
        print(
            "disconnect"
            f" ts={disconnected.get('ts')}"
            f" peer={disconnected.get('peer', '?')}"
            f" reason={disconnected.get('reason', '?')}"
            f" recovery={gap_text}"
        )


if __name__ == "__main__":
    main()
