#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
prefix="$repo_root/host-tools"
distfiles_dir="$repo_root/distfiles"
version="${FINDUTILS_VERSION:-4.10.0}"
archive_name="findutils-${version}.tar.xz"
download_url="https://ftpmirror.gnu.org/findutils/${archive_name}"
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/carthing-findutils.XXXXXX")
archive_path="$distfiles_dir/$archive_name"

cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

mkdir -p "$prefix"
mkdir -p "$distfiles_dir"

if [ -x "$prefix/bin/find" ]; then
    version_line=$("$prefix/bin/find" --version 2>/dev/null | head -n 1 || true)
    case "$version_line" in
        *"GNU findutils"*)
            echo "GNU find already installed at $prefix/bin/find"
            exit 0
            ;;
    esac
fi

echo "Downloading ${archive_name} from ${download_url}"
curl -L --fail --retry 5 --retry-delay 2 --continue-at - -o "$archive_path" "$download_url"

cd "$tmpdir"
cp "$archive_path" "$tmpdir/$archive_name"
tar -xf "$archive_name"
cd "findutils-${version}"

./configure --prefix="$prefix"
make -j"$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
make install

"$prefix/bin/find" --version | head -n 1
