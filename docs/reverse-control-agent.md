# Reverse Control Agent

This repository now includes a host-driven reverse control path for early boot debugging on device `№1`.

Goal:

- do not rely on inbound `ssh`
- do not rely on `httpd` or `telnetd` listening correctly
- let the device poll the host and execute shell commands after stage-2 network is alive

## Components

- Target init script:
  - `overlay/etc/init.d/S09-reverse-agent`
- Target runtime:
  - `overlay/usr/libexec/carthing/reverse-agent.py`
- Host server:
  - `scripts/reverse-control-server.py`
- Host queue helper:
  - `scripts/reverse-agent-enqueue.sh`

## Target Behavior

When enabled, `S09-reverse-agent` starts a small Python loop on the device:

1. poll `CARTHING_REVERSE_AGENT_URL/agent/poll`
2. receive the next queued shell command
3. execute it locally with `/bin/sh -c`
4. POST stdout, stderr, exit code, and timing back to `/agent/result`

The agent writes local state to:

- `/run/carthing/reverse-agent.state`
- `/run/carthing/reverse-agent-pending-result.json`
- `/run/carthing/reverse-agent.log`

## Host Behavior

The host server stores queue and results under:

- `/tmp/carthing-control-server/pending/<device>/`
- `/tmp/carthing-control-server/running/<device>/`
- `/tmp/carthing-control-server/completed/<device>/`

It also logs:

- `beacon.log`
- `poll.log`
- `results.log`

## Default Configuration

Current defaults in `overlay/etc/default/carthing`:

- `CARTHING_REVERSE_AGENT_ENABLE=1`
- `CARTHING_REVERSE_AGENT_URL=http://172.16.42.1:8099`
- `CARTHING_REVERSE_AGENT_DEVICE_ID=device1`
- `CARTHING_REVERSE_AGENT_POLL_INTERVAL=2`
- `CARTHING_REVERSE_AGENT_COMMAND_TIMEOUT=45`
- `CARTHING_REVERSE_AGENT_MAX_OUTPUT=65536`

## Current Runtime Contract

The current image no longer depends on extra IP aliases or one-shot beacon markers.

The stable signals now are:

- `ssh` on `172.16.42.77:22`
- BusyBox `httpd` on `172.16.42.77:8080`
- BusyBox `telnetd` on `172.16.42.77:2323`
- reverse-agent state in `/run/carthing/reverse-agent.state`
- reverse-agent results in `/tmp/carthing-control-server/completed/device1/`

Historical bring-up markers are still documented in `docs/early-userspace-findings-2026-05-11.md`.

## Host Usage

Start the control server:

```sh
python3 scripts/reverse-control-server.py
```

Queue one command:

```sh
sh scripts/reverse-agent-enqueue.sh 'ip addr; ps' device1
```

Check queue/result state:

```sh
curl 'http://172.16.42.1:8099/agent/status?device=device1'
```

Results are written as JSON files in:

```text
/tmp/carthing-control-server/completed/device1/
```

If stale `pending/` or `running/` entries pile up from old bring-up sessions:

```sh
./scripts/reset-reverse-control-state.sh device1
```

That archives them under:

```text
/tmp/carthing-control-server/archive/<timestamp>/device1/
```

## Why This Exists

This is not meant as a permanent management plane.

It is a debugging ingress for the exact stage where:

- `usb0` is alive
- inbound ports are still closed or unreliable
- we need one shell-equivalent foothold before trusting `ssh`
