#!/usr/bin/env bash
set -euo pipefail

HOST="${CARTHING_SSH_HOST:-carthing}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$HOST")
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/artifacts/route-load-$(date +%Y%m%d-%H%M%S)"
OUT_JSON="$OUT_DIR/proof.json"
OUTPUT_KEY="${1:-}"
ROUTE_HOLD_SEC="${ROUTE_HOLD_SEC:-20}"
WAIT_SEC="${WAIT_SEC:-30}"

mkdir -p "$OUT_DIR"

remote_json() {
    local label=$1
    "${SSH[@]}" "python3 - '$label' <<'PY'
import json, sys, time
from pathlib import Path

label = sys.argv[1]
runtime = json.loads(Path('/run/carthing/runtime-bt.json').read_text()).get('bt', {})
state = json.loads(Path('/run/carthing-state/carthing/state.json').read_text())

def row_key(row):
    return row.get('key') or row.get('address') or ''

outputs = []
inputs = []
for row in state.get('devices', []):
    endpoints = row.get('endpoints') or []
    directions = {e.get('direction') for e in endpoints if isinstance(e, dict)}
    caps = set(row.get('capabilities') or [])
    if row.get('role') == 'source' or 'input' in directions or 'audio_input' in caps:
        inputs.append({
            'key': row_key(row),
            'address': row.get('address'),
            'label': row.get('label'),
            'route_input': bool(row.get('route_input')),
        })
    if row.get('role') in ('speaker', 'device') or 'output' in directions or 'audio_output' in caps:
        codecs = []
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            if endpoint.get('direction') != 'output':
                continue
            md = endpoint.get('metadata') or {}
            codecs.extend(md.get('supported_codecs') or [])
        outputs.append({
            'key': row_key(row),
            'address': row.get('address'),
            'label': row.get('label'),
            'role': row.get('role'),
            'route_output': bool(row.get('route_output')),
            'codecs': sorted(set(str(c) for c in codecs)),
        })

    doc = {
        'label': label,
        'ts': time.time(),
        'runtime': {
            'source_connected': runtime.get('connected'),
            'source_peer': runtime.get('peer'),
            'source_name': runtime.get('source'),
            'now_playing': runtime.get('now_playing'),
            'speakers': runtime.get('speakers'),
            'operation_mode': runtime.get('operation_mode'),
            'mode_resources': runtime.get('mode_resources'),
            'route': runtime.get('route'),
        'transfer_active': runtime.get('transfer_active'),
        'resource_policy': runtime.get('resource_policy'),
    },
    'inputs': inputs,
    'outputs': outputs,
}
print(json.dumps(doc, ensure_ascii=False, sort_keys=True))
PY"
}

append_snapshot() {
    local label=$1
    remote_json "$label" >>"$OUT_DIR/snapshots.jsonl"
}

runtime_field() {
    "${SSH[@]}" "python3 - <<'PY'
import json
from pathlib import Path
bt=json.loads(Path('/run/carthing/runtime-bt.json').read_text()).get('bt', {})
mr=bt.get('mode_resources') or {}
rp=bt.get('resource_policy') or {}
cpu=(rp.get('cpu_policies') or [{}])[0]
print('|'.join([
  str(bt.get('operation_mode')),
  str(mr.get('actual_receiver_stream')),
  str(mr.get('actual_receiver_connecting')),
  str(mr.get('actual_route_patchbay')),
  str(mr.get('actual_standby_loop')),
  str(cpu.get('governor')),
  str((rp.get('zram') or {}).get('active')),
]))
PY"
}

wait_for_mode() {
    local want_mode=$1
    local deadline=$((SECONDS + WAIT_SEC))
    while [ "$SECONDS" -lt "$deadline" ]; do
        IFS='|' read -r mode _receiver _connecting _patchbay _standby _governor _zram < <(runtime_field)
        if [ "$mode" = "$want_mode" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

choose_output() {
    if [ -n "$OUTPUT_KEY" ]; then
        printf '%s\n' "$OUTPUT_KEY"
        return
    fi
    "${SSH[@]}" "python3 - <<'PY'
import json
from pathlib import Path
state=json.loads(Path('/run/carthing-state/carthing/state.json').read_text())
rows=[]
for row in state.get('devices', []):
    endpoints=row.get('endpoints') or []
    directions={e.get('direction') for e in endpoints if isinstance(e, dict)}
    caps=set(row.get('capabilities') or [])
    if row.get('role') not in ('speaker','device') and 'output' not in directions and 'audio_output' not in caps:
        continue
    codecs=[]
    for endpoint in endpoints:
        if not isinstance(endpoint, dict) or endpoint.get('direction') != 'output':
            continue
        codecs.extend((endpoint.get('metadata') or {}).get('supported_codecs') or [])
    key=row.get('key') or row.get('address')
    if not key:
        continue
    score=(10 if 'AAC' in codecs else 0, len(codecs), key)
    rows.append((score, key))
if not rows:
    raise SystemExit('no route output candidates')
print(sorted(rows, reverse=True)[0][1])
PY"
}

send_route_cmd() {
    local cmd=$1
    "${SSH[@]}" "printf '%s\n' '$cmd' >/run/carthing/route-cmd"
}

output=$(choose_output)
printf 'route-load proof output=%s hold=%ss wait=%ss\n' "$output" "$ROUTE_HOLD_SEC" "$WAIT_SEC" | tee "$OUT_DIR/summary.txt"

append_snapshot "before"
send_route_cmd "select $output"
sleep 2
append_snapshot "selected-output"
send_route_cmd "activate"
if ! wait_for_mode "commutator"; then
    append_snapshot "commutator-timeout"
    echo "failed: commutator mode did not appear" | tee -a "$OUT_DIR/summary.txt"
    exit 1
fi
sleep "$ROUTE_HOLD_SEC"
append_snapshot "commutator-hold"
send_route_cmd "select carthing"
sleep 1
send_route_cmd "activate"
if ! wait_for_mode "playnow"; then
    append_snapshot "playnow-timeout"
    echo "failed: playnow mode did not return" | tee -a "$OUT_DIR/summary.txt"
    exit 1
fi
sleep 3
append_snapshot "after"

python3 - "$OUT_DIR/snapshots.jsonl" "$OUT_JSON" <<'PY'
import json, sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
snapshots = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]

def slim(snapshot):
    runtime = snapshot.get('runtime') or {}
    resources = runtime.get('mode_resources') or {}
    policy = runtime.get('resource_policy') or {}
    cpu = (policy.get('cpu_policies') or [{}])[0]
    zram = policy.get('zram') or {}
    route = runtime.get('route') or {}
    speakers = runtime.get('speakers') or []
    return {
        'label': snapshot.get('label'),
        'source_connected': runtime.get('source_connected'),
        'source_peer': runtime.get('source_peer'),
        'source_name': runtime.get('source_name'),
        'now_playing_title': (runtime.get('now_playing') or {}).get('title'),
        'now_playing_playing': (runtime.get('now_playing') or {}).get('playing'),
        'operation_mode': runtime.get('operation_mode'),
        'route_active': route.get('active'),
        'route_input': route.get('input'),
        'route_output': route.get('output'),
        'speakers': [
            {
                'key': row.get('key'),
                'connected': row.get('connected'),
                'standby': row.get('standby'),
                'connecting': row.get('connecting'),
                'status': row.get('status'),
            }
            for row in speakers
        ],
        'governor': cpu.get('governor'),
        'zram_active': zram.get('active'),
        'zram_used_kb': zram.get('swap_used_kb'),
        'actual_standby_loop': resources.get('actual_standby_loop'),
        'actual_receiver_stream': resources.get('actual_receiver_stream'),
        'actual_receiver_connecting': resources.get('actual_receiver_connecting'),
        'actual_route_patchbay': resources.get('actual_route_patchbay'),
        'actual_speaker_scan': resources.get('actual_speaker_scan'),
        'actual_source_stream': resources.get('actual_source_stream'),
        'packets_forwarded': resources.get('packets_forwarded'),
        'packets_dropped': resources.get('packets_dropped'),
    }

doc = {
    'schema': 1,
    'snapshots': snapshots,
    'summary': [slim(snapshot) for snapshot in snapshots],
}
target.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
for row in doc['summary']:
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
PY

echo "proof: $OUT_JSON" | tee -a "$OUT_DIR/summary.txt"
