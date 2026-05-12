#!/bin/sh
set -eu

device=${1:-device1}
state_dir=${CARTHING_CONTROL_STATE_DIR:-/tmp/carthing-control-server}
stamp=$(date +%Y%m%d-%H%M%S)
archive_root="$state_dir/archive/$stamp/$device"

move_bucket() {
    bucket=$1
    src="$state_dir/$bucket/$device"
    dst="$archive_root/$bucket"

    [ -d "$src" ] || return 0

    count=$(find "$src" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')
    [ "$count" -gt 0 ] || return 0

    mkdir -p "$dst"
    find "$src" -maxdepth 1 -type f -name '*.json' -exec mv {} "$dst/" \;
    echo "$bucket: archived $count -> $dst"
}

move_bucket pending
move_bucket running

mkdir -p "$state_dir/pending/$device" "$state_dir/running/$device" "$state_dir/completed/$device"

echo "state reset complete for $device"
echo "archive root: $archive_root"
