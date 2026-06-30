# Car Thing soak monitoring

The monitor runs independently of Terminal under:

```sh
launchctl print gui/$(id -u)/com.carthing.soak-monitor
```

It appends device snapshots, CTSP logs, Assistant timings, macOS process
health, and the device connection journal to:

```text
~/Library/Logs/CarThing/soak.jsonl
```

No Bluetooth control is performed by the monitor. Device snapshots use the
existing USB/NCM SSH management channel; all product data and controls continue
to use Bluetooth CTSP.

Install or refresh the LaunchAgent:

```sh
scripts/install-soak-monitor-launchd.sh
```

Summarize the current interval:

```sh
scripts/report-soak.py --hours 2
scripts/report-soak.py --hours 24
```

The report separates:

- iPhone connection availability and lifecycle events;
- CTSP RTT, reconnect, Bluetooth, and capture-to-Mac latency;
- Whisper queue/STT latency;
- LLM response latency;
- source error/event counts.

The JSONL log is append-only. Cursor state used to follow existing source logs
without duplicating old content lives in:

```text
~/Library/Logs/CarThing/soak-cursors.json
```
