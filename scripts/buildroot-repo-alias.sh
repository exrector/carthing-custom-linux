#!/bin/sh

prepare_buildroot_repo_alias() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        echo "CARTHING_REPO_ROOT is not set" >&2
        return 1
    fi

    alias_root="${TMPDIR:-/tmp}/carthing-custom-linux-repo"
    ln -sfn "$CARTHING_REPO_ROOT" "$alias_root"

    CARTHING_REPO_ALIAS_ROOT="$alias_root"
    CARTHING_BR2_EXTERNAL="$alias_root/buildroot-external"
    export CARTHING_REPO_ALIAS_ROOT CARTHING_BR2_EXTERNAL
}
