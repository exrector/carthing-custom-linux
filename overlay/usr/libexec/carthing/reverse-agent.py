#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import time
import traceback
import urllib.parse
import urllib.request


CONFIG_PATH = "/etc/default/carthing"
STATE_DIR = "/run/carthing"
RESULT_PATH = STATE_DIR + "/reverse-agent-pending-result.json"
STATE_PATH = STATE_DIR + "/reverse-agent.state"
TRACEBACK_PATH = STATE_DIR + "/reverse-agent.traceback"
VERSION_PATH = STATE_DIR + "/reverse-agent.version"
DEFAULT_BASE_URL = "http://172.16.42.1:8099"
DEFAULT_BEACON_URL = ""
DEFAULT_DEVICE_ID = "device1"
DEFAULT_POLL_INTERVAL = 2
DEFAULT_COMMAND_TIMEOUT = 45
DEFAULT_MAX_OUTPUT = 65536

BASE_URL = DEFAULT_BASE_URL
BEACON_URL = DEFAULT_BEACON_URL
DEVICE_ID = DEFAULT_DEVICE_ID
POLL_INTERVAL = DEFAULT_POLL_INTERVAL
COMMAND_TIMEOUT = DEFAULT_COMMAND_TIMEOUT
MAX_OUTPUT = DEFAULT_MAX_OUTPUT


def ensure_state_dir():
    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)


def load_config():
    config = {}
    with open(CONFIG_PATH, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key] = value.strip().strip('"')
    return config


def parse_int_config(config, key, default, minimum):
    raw = config.get(key)
    if raw in (None, ""):
        return default
    value = int(raw)
    if value < minimum:
        return minimum
    return value


def apply_runtime_config(config):
    global BASE_URL
    global BEACON_URL
    global DEVICE_ID
    global POLL_INTERVAL
    global COMMAND_TIMEOUT
    global MAX_OUTPUT

    BASE_URL = config.get("CARTHING_REVERSE_AGENT_URL", DEFAULT_BASE_URL).rstrip("/")
    BEACON_URL = config.get("CARTHING_DEBUG_BEACON_URL", DEFAULT_BEACON_URL).rstrip("?")
    DEVICE_ID = config.get("CARTHING_REVERSE_AGENT_DEVICE_ID", DEFAULT_DEVICE_ID) or DEFAULT_DEVICE_ID
    POLL_INTERVAL = parse_int_config(
        config,
        "CARTHING_REVERSE_AGENT_POLL_INTERVAL",
        DEFAULT_POLL_INTERVAL,
        1,
    )
    COMMAND_TIMEOUT = parse_int_config(
        config,
        "CARTHING_REVERSE_AGENT_COMMAND_TIMEOUT",
        DEFAULT_COMMAND_TIMEOUT,
        1,
    )
    MAX_OUTPUT = parse_int_config(
        config,
        "CARTHING_REVERSE_AGENT_MAX_OUTPUT",
        DEFAULT_MAX_OUTPUT,
        1024,
    )


def write_text(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def read_text(path):
    with open(path, "r") as fh:
        return fh.read()


def write_state(message):
    ensure_state_dir()
    write_text(STATE_PATH, message + "\n")


def beacon(*args):
    try:
        subprocess.Popen(
            ["/usr/libexec/carthing/beacon"] + list(args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).wait()
    except Exception:
        pass


def beacon_http(event, *args):
    if not BEACON_URL:
        return
    try:
        params = [("event", event)]
        for extra in args:
            params.append(("arg", extra))
        request = urllib.request.Request("{}?{}".format(BEACON_URL, urllib.parse.urlencode(params)))
        response = urllib.request.urlopen(request, timeout=2)
        try:
            response.read()
        finally:
            response.close()
    except Exception:
        pass


def mark_ip(ip_address):
    try:
        subprocess.Popen(
            ["/usr/libexec/carthing/debug-ip-mark", ip_address],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).wait()
    except Exception:
        pass


def decode_payload(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def http_get_json(path, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request("{}{}?{}".format(BASE_URL, path, query))
    response = urllib.request.urlopen(request, timeout=5)
    try:
        return json.loads(decode_payload(response.read()))
    finally:
        response.close()


def http_post_json(path, params, payload):
    query = urllib.parse.urlencode(params)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "{}{}?{}".format(BASE_URL, path, query),
        data=data,
        headers={"Content-Type": "application/json"},
    )
    response = urllib.request.urlopen(request, timeout=8)
    try:
        return json.loads(decode_payload(response.read()))
    finally:
        response.close()


def trim_text(value):
    if len(value) <= MAX_OUTPUT:
        return value
    keep = MAX_OUTPUT // 2
    return value[:keep] + "\n...[truncated]...\n" + value[-keep:]


def trim_diag(value):
    output = []
    for ch in str(value):
        if ch.isalnum() or ch in "._:-":
            output.append(ch)
        else:
            output.append("_")
    return "".join(output).strip("_")[:96] or "empty"


def run_command_via_system(command_id, shell_command, completed):
    script_path = STATE_DIR + "/reverse-agent-command.sh"
    stdout_path = STATE_DIR + "/reverse-agent-command.stdout"
    stderr_path = STATE_DIR + "/reverse-agent-command.stderr"
    status_path = STATE_DIR + "/reverse-agent-command.status"
    timeout_path = STATE_DIR + "/reverse-agent-command.timeout"

    for path in (stdout_path, stderr_path, status_path, timeout_path):
        try:
            os.remove(path)
        except OSError:
            pass

    write_text(script_path, "#!/bin/sh\n" + shell_command + "\n")
    os.chmod(script_path, 0o700)

    wrapper = """
out={out}
err={err}
status_file={status_file}
timeout_file={timeout_file}
script={script}
sh "$script" >"$out" 2>"$err" &
pid=$!
timed_out=0
elapsed=0
while kill -0 "$pid" 2>/dev/null; do
    if [ "$elapsed" -ge {timeout} ]; then
        kill "$pid" 2>/dev/null || true
        timed_out=1
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done
wait "$pid"
status=$?
[ "$timed_out" -eq 1 ] && status=124
printf '%s' "$status" >"$status_file"
printf '%s' "$timed_out" >"$timeout_file"
""".format(
        out=shlex.quote(stdout_path),
        err=shlex.quote(stderr_path),
        status_file=shlex.quote(status_path),
        timeout_file=shlex.quote(timeout_path),
        script=shlex.quote(script_path),
        timeout=COMMAND_TIMEOUT,
    )

    os.system(wrapper)

    completed["exit_code"] = int(read_text(status_path).strip() or "1")
    completed["stdout"] = trim_text(read_text(stdout_path) if os.path.exists(stdout_path) else "")
    completed["stderr"] = trim_text(read_text(stderr_path) if os.path.exists(stderr_path) else "")
    completed["timed_out"] = (read_text(timeout_path).strip() == "1") if os.path.exists(timeout_path) else False


def run_command(command_id, shell_command):
    started = time.time()
    completed = {
        "device_id": DEVICE_ID,
        "command_id": command_id,
        "command": shell_command,
        "started_at": started,
    }
    mark_ip("172.16.42.229")
    beacon("reverse-command-start", command_id)
    beacon_http("reverse-agent-run-enter", command_id)
    write_state("running {}".format(command_id))
    try:
        process = subprocess.Popen(
            ["/bin/sh", "-c", shell_command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        mark_ip("172.16.42.230")
        beacon_http("reverse-agent-run-spawned", command_id)
        try:
            stdout_data, stderr_data = process.communicate(timeout=COMMAND_TIMEOUT)
            completed["exit_code"] = process.returncode
            completed["stdout"] = trim_text(decode_payload(stdout_data))
            completed["stderr"] = trim_text(decode_payload(stderr_data))
            completed["timed_out"] = False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_data, stderr_data = process.communicate()
            completed["exit_code"] = 124
            completed["stdout"] = trim_text(decode_payload(stdout_data))
            completed["stderr"] = trim_text(decode_payload(stderr_data) + "\ncommand timed out")
            completed["timed_out"] = True
    except Exception as exc:
        beacon_http("reverse-agent-popen-failed", exc.__class__.__name__, trim_diag(exc))
        run_command_via_system(command_id, shell_command, completed)
    mark_ip("172.16.42.231")
    completed["finished_at"] = time.time()
    write_text(RESULT_PATH, json.dumps(completed))
    mark_ip("172.16.42.232")
    write_state("completed {}".format(command_id))
    beacon("reverse-command-done", command_id)
    beacon_http("reverse-agent-run-done", command_id)


def flush_result():
    if not os.path.exists(RESULT_PATH):
        return True
    try:
        payload = json.loads(read_text(RESULT_PATH))
        response = http_post_json(
            "/agent/result",
            {"device": DEVICE_ID, "id": payload["command_id"]},
            payload,
        )
        if response.get("ok"):
            try:
                os.remove(RESULT_PATH)
            except OSError:
                pass
            mark_ip("172.16.42.234")
            write_state("idle acked {}".format(payload["command_id"]))
            beacon("reverse-result-acked", payload["command_id"])
            return True
    except Exception as exc:
        mark_ip("172.16.42.235")
        write_state("result-post-failed {}".format(exc))
        write_text(TRACEBACK_PATH, traceback.format_exc())
    return False


def poll_once():
    try:
        response = http_get_json("/agent/poll", {"device": DEVICE_ID})
        command = response.get("command")
        if not command:
            write_state("idle")
            return
        mark_ip("172.16.42.237")
        beacon_http("reverse-agent-got-command", command["id"])
        run_command(command["id"], command["shell"])
    except Exception as exc:
        mark_ip("172.16.42.233")
        write_state("poll-failed {}".format(exc))
        write_text(TRACEBACK_PATH, traceback.format_exc())
        beacon_http("reverse-agent-poll-failed", exc.__class__.__name__, trim_diag(exc))


def main():
    ensure_state_dir()
    apply_runtime_config(load_config())
    write_text(VERSION_PATH, "py-main-v4\n")
    write_state("starting")
    mark_ip("172.16.42.236")
    beacon("reverse-agent-entry", DEVICE_ID)
    beacon_http("reverse-agent-py-start", DEVICE_ID)
    while True:
        if flush_result():
            poll_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        mark_ip("172.16.42.187")
        write_state("fatal {}: {}".format(exc.__class__.__name__, exc))
        try:
            import traceback

            write_text(TRACEBACK_PATH, traceback.format_exc())
        except Exception:
            pass
        raise
