#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
prefix="$repo_root/host-tools"
distfiles_dir="$repo_root/distfiles"
version="${SED_VERSION:-4.9}"
archive_name="sed-${version}.tar.xz"
download_url="https://ftpmirror.gnu.org/sed/${archive_name}"
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/carthing-sed.XXXXXX")
archive_path="$distfiles_dir/$archive_name"

cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

mkdir -p "$prefix"
mkdir -p "$distfiles_dir"

if [ -x "$prefix/bin/sed" ]; then
    version_line=$("$prefix/bin/sed" --version 2>/dev/null | head -n 1 || true)
    case "$version_line" in
        *"GNU sed"*)
            echo "GNU sed already installed at $prefix/bin/sed"
            exit 0
            ;;
    esac
fi

echo "Downloading ${archive_name} from ${download_url}"
curl -L --fail --retry 5 --retry-delay 2 --continue-at - -o "$archive_path" "$download_url"

cd "$tmpdir"
cp "$archive_path" "$tmpdir/$archive_name"
tar -xf "$archive_name"
cd "sed-${version}"

./configure --prefix="$prefix"
make -j"$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
make install

"$prefix/bin/sed" --version | head -n 1
