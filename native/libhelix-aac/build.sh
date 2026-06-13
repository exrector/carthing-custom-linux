#!/bin/sh
set -eu

cd "$(dirname "$0")"

sources="
shim/shim.c
aacdec.c
aactabs.c
bitstream.c
buffers.c
dct4.c
decelmnt.c
dequant.c
fft.c
filefmt.c
huffman.c
hufftabs.c
imdct.c
noiseless.c
pns.c
stproc.c
tns.c
trigtabs.c
"

case "${1:-device}" in
  device)
    clang -target aarch64-unknown-linux-gnu \
      -DARDUINO -O2 -fPIC -shared -nostdlib -ffreestanding \
      -Ishim -I. \
      -o libhelixaac.so $sources
    ;;
  host)
    out="${2:-/tmp/libhelixaac-host.dylib}"
    clang -DARDUINO -O2 -fPIC -dynamiclib \
      -Ishim -I. \
      -o "$out" $sources
    ;;
  *)
    echo "usage: $0 [device|host [host-output]]" >&2
    exit 2
    ;;
esac
