#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <path> [path...]"
    exit 1
fi

owner=$(id -un)
group=$(id -gn)

need_fix=0
paths_to_fix=""

for path in "$@"; do
    [ -e "$path" ] || continue
    if find "$path" -user root -print -quit | grep -q .; then
        need_fix=1
        paths_to_fix="$paths_to_fix
$path"
    fi
done

[ "$need_fix" -eq 1 ] || exit 0

if ! sudo -n true >/dev/null 2>&1; then
    echo "error: root-owned Buildroot paths found, but passwordless sudo is unavailable" >&2
    exit 1
fi

printf '%s\n' "$paths_to_fix" | while IFS= read -r path; do
    [ -n "$path" ] || continue
    echo "repairing ownership under $path"
    sudo -n chown -R "$owner:$group" "$path"
done
