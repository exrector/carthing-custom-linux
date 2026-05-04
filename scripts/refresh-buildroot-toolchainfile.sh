#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <buildroot-output-dir>" >&2
    exit 1
fi

output_dir=$1
config_file="$output_dir/.config"
toolchain_file="$output_dir/host/share/buildroot/toolchainfile.cmake"

[ -f "$config_file" ] || exit 0
[ -f "$toolchain_file" ] || exit 0

if grep -q '^BR2_INSTALL_LIBSTDCPP=y$' "$config_file"; then
    cxx_enabled=1
else
    cxx_enabled=0
fi

if grep -q '^BR2_TOOLCHAIN_HAS_FORTRAN=y$' "$config_file"; then
    fortran_enabled=1
else
    fortran_enabled=0
fi

python3 - "$toolchain_file" "$cxx_enabled" "$fortran_enabled" <<'PY'
from pathlib import Path
import re
import sys

toolchain_path = Path(sys.argv[1])
cxx_enabled = sys.argv[2] == "1"
fortran_enabled = sys.argv[3] == "1"
text = toolchain_path.read_text()
updated = text

def replace_guard(source: str, marker: str, enabled: bool) -> str:
    pattern = re.compile(
        rf"if\((?:0|1)\)\n(?=  if\(NOT DEFINED {re.escape(marker)}\))"
    )

    expected = "if(1)\n" if enabled else "if(0)\n"

    def repl(match: re.Match[str]) -> str:
        return expected

    result, count = pattern.subn(repl, source, count=1)
    if count == 0:
        raise SystemExit(f"failed to find guard for {marker} in {toolchain_path}")
    return result

updated = replace_guard(updated, "CMAKE_CXX_FLAGS_DEBUG", cxx_enabled)
updated = replace_guard(updated, "CMAKE_Fortran_FLAGS_DEBUG", fortran_enabled)

if updated != text:
    toolchain_path.write_text(updated)
PY
