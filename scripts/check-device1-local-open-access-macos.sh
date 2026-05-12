#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
usage: check-device1-local-open-access-macos.sh [--host IP] [--identity KEY]

Bring up the macOS USB host link for device №1 and check the intentionally
open local access profile:

- SSH on port 22
- BusyBox httpd on port 8080
- BusyBox telnetd on port 2323

If an identity file is provided and exists, the script also attempts one
non-interactive SSH login.
EOF
}

host_ip=${HOST_IP:-172.16.42.77}
identity=${IDENTITY_FILE:-$HOME/.ssh/id_rsa}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            shift
            [ "$#" -gt 0 ] || { echo "missing value for --host" >&2; exit 1; }
            host_ip=$1
            ;;
        --identity)
            shift
            [ "$#" -gt 0 ] || { echo "missing value for --identity" >&2; exit 1; }
            identity=$1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

"$repo_root/scripts/bring-up-device1-normal-boot-macos.sh"

python3 - "$host_ip" <<'PY'
import socket
import sys

host = sys.argv[1]
failed = False
for port in (22, 8080, 2323):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((host, port))
    except Exception as exc:
        print(f"tcp_{port}: fail {type(exc).__name__}: {exc}")
        failed = True
    else:
        print(f"tcp_{port}: ok")
    finally:
        s.close()
if failed:
    sys.exit(1)
PY

if [ -f "$identity" ]; then
    ssh -i "$identity" \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        -o ConnectTimeout=3 \
        root@"$host_ip" 'id' || true
else
    echo "ssh_identity: missing $identity"
fi
