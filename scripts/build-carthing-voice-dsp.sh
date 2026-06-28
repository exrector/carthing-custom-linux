#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cc=${CC:-/opt/homebrew/bin/aarch64-linux-gnu-gcc}
speex_prefix=${SPEEXDSP_PREFIX:-/tmp/carthing-speexdsp}

if [ ! -f "$speex_prefix/lib/libspeexdsp.so" ]; then
    echo "missing cross-built SpeexDSP at $speex_prefix" >&2
    exit 1
fi

"$cc" -O3 -fPIC -shared \
    -I"$speex_prefix/include" \
    "$repo_root/native/carthing_voice_dsp.c" \
    -L"$speex_prefix/lib" -lspeexdsp -lm \
    -Wl,-rpath,'$ORIGIN' \
    -o "$repo_root/overlay/usr/lib/carthing/libcarthing_voice_dsp.so"

"${STRIP:-/opt/homebrew/bin/aarch64-linux-gnu-strip}" \
    "$repo_root/overlay/usr/lib/carthing/libcarthing_voice_dsp.so"

echo "built overlay/usr/lib/carthing/libcarthing_voice_dsp.so"
