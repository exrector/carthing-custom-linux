#!/bin/sh

sanitize_path() {
    old_ifs=$IFS
    clean_path=""
    IFS=:
    for entry in $PATH; do
        case "$entry" in
            *" "*|*"	"*|*"
"*)
                continue
                ;;
        esac
        [ -n "$entry" ] || continue
        clean_path="${clean_path:+$clean_path:}$entry"
    done
    IFS=$old_ifs

    if [ -n "$clean_path" ]; then
        PATH="$clean_path"
        export PATH
    fi
}

prepend_path_dir() {
    path_dir="$1"
    [ -d "$path_dir" ] || return 0

    case ":$PATH:" in
        *":$path_dir:"*)
            ;;
        *)
            PATH="$path_dir:$PATH"
            export PATH
            ;;
    esac
}

prepend_wrapper_tool() {
    tool_name="$1"
    tool_path="$2"
    wrapper_dir="${TMPDIR:-/tmp}/carthing-buildroot-host-tools"

    mkdir -p "$wrapper_dir"
    ln -sf "$tool_path" "$wrapper_dir/$tool_name"

    case ":$PATH:" in
        *":$wrapper_dir:"*)
            ;;
        *)
            PATH="$wrapper_dir:$PATH"
            export PATH
            ;;
    esac
}

prepend_repo_host_bin() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 0
    fi

    prepend_path_dir "$CARTHING_REPO_ROOT/host-tools/bin"
}

prefer_repo_local_patch() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 1
    fi

    local_patch="$CARTHING_REPO_ROOT/host-tools/bin/patch"
    if [ -x "$local_patch" ]; then
        version_line=$("$local_patch" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU patch"*)
                prepend_wrapper_tool patch "$local_patch"
                return 0
                ;;
        esac
    fi

    return 1
}

prefer_repo_local_install() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 1
    fi

    local_install="$CARTHING_REPO_ROOT/host-tools/bin/install"
    if [ -x "$local_install" ]; then
        version_line=$("$local_install" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                prepend_wrapper_tool install "$local_install"
                return 0
                ;;
        esac
    fi

    return 1
}

prefer_repo_local_sed() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 1
    fi

    local_sed="$CARTHING_REPO_ROOT/host-tools/bin/sed"
    if [ -x "$local_sed" ]; then
        version_line=$("$local_sed" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU sed"*)
                prepend_wrapper_tool sed "$local_sed"
                return 0
                ;;
        esac
    fi

    return 1
}

prefer_repo_local_cp() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 1
    fi

    local_cp="$CARTHING_REPO_ROOT/host-tools/bin/cp"
    if [ -x "$local_cp" ]; then
        version_line=$("$local_cp" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                prepend_wrapper_tool cp "$local_cp"
                return 0
                ;;
        esac
    fi

    return 1
}

prefer_repo_local_chmod() {
    if [ -z "${CARTHING_REPO_ROOT:-}" ]; then
        return 1
    fi

    local_chmod="$CARTHING_REPO_ROOT/host-tools/bin/chmod"
    if [ -x "$local_chmod" ]; then
        version_line=$("$local_chmod" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                prepend_wrapper_tool chmod "$local_chmod"
                return 0
                ;;
        esac
    fi

    return 1
}

ensure_gnu_patch() {
    if prefer_repo_local_patch; then
        return 0
    fi

    if command -v patch >/dev/null 2>&1; then
        version_line=$(patch --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU patch"*)
                return 0
                ;;
        esac
    fi

    if command -v gpatch >/dev/null 2>&1; then
        prepend_wrapper_tool patch "$(command -v gpatch)"
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix gpatch 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/libexec/gnubin/patch" ]; then
            prepend_wrapper_tool patch "$brew_prefix/libexec/gnubin/patch"
            return 0
        fi
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/gpatch" ]; then
            prepend_wrapper_tool patch "$brew_prefix/bin/gpatch"
            return 0
        fi
    fi

    return 1
}

ensure_gnu_install() {
    if prefer_repo_local_install; then
        return 0
    fi

    if command -v install >/dev/null 2>&1; then
        version_line=$(install --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                return 0
                ;;
        esac
    fi

    if command -v ginstall >/dev/null 2>&1; then
        prepend_wrapper_tool install "$(command -v ginstall)"
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix coreutils 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/libexec/gnubin/install" ]; then
            prepend_wrapper_tool install "$brew_prefix/libexec/gnubin/install"
            return 0
        fi
    fi

    return 1
}

ensure_gnu_sed() {
    if prefer_repo_local_sed; then
        return 0
    fi

    if command -v sed >/dev/null 2>&1; then
        version_line=$(sed --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU sed"*)
                return 0
                ;;
        esac
    fi

    if command -v gsed >/dev/null 2>&1; then
        prepend_wrapper_tool sed "$(command -v gsed)"
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix gnu-sed 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/libexec/gnubin/sed" ]; then
            prepend_wrapper_tool sed "$brew_prefix/libexec/gnubin/sed"
            return 0
        fi
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/gsed" ]; then
            prepend_wrapper_tool sed "$brew_prefix/bin/gsed"
            return 0
        fi
    fi

    return 1
}

ensure_gnu_cp() {
    if prefer_repo_local_cp; then
        return 0
    fi

    if command -v cp >/dev/null 2>&1; then
        version_line=$(cp --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                return 0
                ;;
        esac
    fi

    if command -v gcp >/dev/null 2>&1; then
        prepend_wrapper_tool cp "$(command -v gcp)"
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix coreutils 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/libexec/gnubin/cp" ]; then
            prepend_wrapper_tool cp "$brew_prefix/libexec/gnubin/cp"
            return 0
        fi
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/gcp" ]; then
            prepend_wrapper_tool cp "$brew_prefix/bin/gcp"
            return 0
        fi
    fi

    return 1
}

ensure_gnu_chmod() {
    if prefer_repo_local_chmod; then
        return 0
    fi

    if command -v chmod >/dev/null 2>&1; then
        version_line=$(chmod --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"GNU coreutils"*)
                return 0
                ;;
        esac
    fi

    if command -v gchmod >/dev/null 2>&1; then
        prepend_wrapper_tool chmod "$(command -v gchmod)"
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix coreutils 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/libexec/gnubin/chmod" ]; then
            prepend_wrapper_tool chmod "$brew_prefix/libexec/gnubin/chmod"
            return 0
        fi
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/gchmod" ]; then
            prepend_wrapper_tool chmod "$brew_prefix/bin/gchmod"
            return 0
        fi
    fi

    return 1
}

is_modern_gnu_bash() {
    candidate="$1"
    [ -x "$candidate" ] || return 1

    version_line=$("$candidate" --version 2>/dev/null | head -n 1 || true)
    case "$version_line" in
        "GNU bash, version "[4-9]*|"GNU bash, version "[1-9][0-9]*)
            return 0
            ;;
    esac

    return 1
}

ensure_modern_bash() {
    if command -v bash >/dev/null 2>&1; then
        current_bash=$(command -v bash)
        if is_modern_gnu_bash "$current_bash"; then
            prepend_wrapper_tool bash "$current_bash"
            return 0
        fi
    fi

    if [ -x /opt/homebrew/bin/bash ] && is_modern_gnu_bash /opt/homebrew/bin/bash; then
        prepend_wrapper_tool bash /opt/homebrew/bin/bash
        return 0
    fi

    if [ -x /usr/local/bin/bash ] && is_modern_gnu_bash /usr/local/bin/bash; then
        prepend_wrapper_tool bash /usr/local/bin/bash
        return 0
    fi

    if command -v brew >/dev/null 2>&1; then
        brew_prefix=$(brew --prefix bash 2>/dev/null || true)
        if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/bash" ] && is_modern_gnu_bash "$brew_prefix/bin/bash"; then
            prepend_wrapper_tool bash "$brew_prefix/bin/bash"
            return 0
        fi
    fi

    return 1
}

pick_gnu_compiler() {
    for candidate in "$@"; do
        [ -n "$candidate" ] || continue
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi

        version_line=$("$candidate" --version 2>/dev/null | head -n 1 || true)
        case "$version_line" in
            *"Apple clang"*)
                continue
                ;;
        esac

        command -v "$candidate"
        return 0
    done

    return 1
}

prepare_buildroot_host_env() {
    sanitize_path
    prepend_repo_host_bin
    if ! ensure_modern_bash; then
        echo "missing modern GNU bash: provide bash >= 4 in PATH" >&2
        return 1
    fi
    if ! ensure_gnu_patch; then
        echo "missing GNU patch: run ./scripts/install-buildroot-host-tools.sh or provide GNU patch as 'patch' in PATH" >&2
        return 1
    fi
    if ! ensure_gnu_install; then
        echo "missing GNU install: run ./scripts/install-buildroot-host-tools.sh or provide GNU install as 'install' in PATH" >&2
        return 1
    fi
    if ! ensure_gnu_sed; then
        echo "missing GNU sed: run ./scripts/install-buildroot-host-tools.sh or provide GNU sed as 'sed' in PATH" >&2
        return 1
    fi
    if ! ensure_gnu_cp; then
        echo "missing GNU cp: run ./scripts/install-buildroot-host-tools.sh or provide GNU cp as 'cp' in PATH" >&2
        return 1
    fi
    if ! ensure_gnu_chmod; then
        echo "missing GNU chmod: run ./scripts/install-buildroot-host-tools.sh or provide GNU chmod as 'chmod' in PATH" >&2
        return 1
    fi

    HOSTCC=$(pick_gnu_compiler gcc-15 gcc-14 gcc-13 gcc-12 gcc || command -v gcc || true)
    HOSTCXX=$(pick_gnu_compiler g++-15 g++-14 g++-13 g++-12 g++ || command -v g++ || true)

    if [ -n "${HOSTCC:-}" ]; then
        export HOSTCC
    fi

    if [ -n "${HOSTCXX:-}" ]; then
        export HOSTCXX
    fi
}
