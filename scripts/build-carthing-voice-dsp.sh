#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cc=${CC:-/opt/homebrew/bin/aarch64-linux-gnu-gcc}
speex_prefix=${SPEEXDSP_PREFIX:-/tmp/carthing-speexdsp}
opus_prefix=${OPUS_PREFIX:-/tmp/carthing-opus-prefix}

if [ ! -f "$speex_prefix/lib/libspeexdsp.so" ]; then
    echo "missing cross-built SpeexDSP at $speex_prefix" >&2
    exit 1
fi
if [ ! -f "$opus_prefix/lib/libopus.so" ]; then
    echo "missing cross-built Opus at $opus_prefix" >&2
    exit 1
fi

"$cc" -O3 -fPIC -shared \
    -I"$speex_prefix/include" \
    -I"$opus_prefix/include" \
    "$repo_root/native/carthing_voice_dsp.c" \
    -L"$speex_prefix/lib" -lspeexdsp \
    -L"$opus_prefix/lib" -lopus -lm \
    -Wl,-rpath,/usr/lib/carthing \
    -o "$repo_root/overlay/usr/lib/carthing/libcarthing_voice_dsp.so"

"${STRIP:-/opt/homebrew/bin/aarch64-linux-gnu-strip}" \
    "$repo_root/overlay/usr/lib/carthing/libcarthing_voice_dsp.so"
install -m 755 \
    "$opus_prefix/lib/libopus.so.0.11.1" \
    "$repo_root/overlay/usr/lib/carthing/libopus.so.0"
"${STRIP:-/opt/homebrew/bin/aarch64-linux-gnu-strip}" \
    "$repo_root/overlay/usr/lib/carthing/libopus.so.0"

echo "built overlay/usr/lib/carthing/libcarthing_voice_dsp.so"
