#!/usr/bin/env python3
"""Эталонный тест sbc_decoder против ffmpeg (кодер И декодер — референс).
Запуск на Mac: python3 tools/test_sbc_decoder.py  (нужен ffmpeg с sbc)."""
import os, struct, subprocess, sys, math, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "overlay", "usr", "lib", "carthing"))
from sbc_decoder import SbcDecoder

def run(tmp):
    src = os.path.join(tmp, "src.raw")
    sbc = os.path.join(tmp, "test.sbc")
    ref = os.path.join(tmp, "ref.raw")
    # 2с микс синусов, чтобы спектр был нетривиальный
    with open(src, "wb") as f:
        for i in range(44100 * 2):
            t = i / 44100.0
            v = int(9000 * math.sin(2*math.pi*440*t) + 4000 * math.sin(2*math.pi*1320*t))
            f.write(struct.pack("<hh", v, int(v*0.7)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "44100", "-ac", "2",
                    "-i", src, "-c:a", "sbc", "-b:a", "328k", sbc], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", sbc,
                    "-f", "s16le", "-ar", "44100", "-ac", "2", ref], check=True)
    data = open(sbc, "rb").read()
    dec = SbcDecoder()
    out = dec.decode("sbc-raw", data)
    refpcm = open(ref, "rb").read()
    n = min(len(out), len(refpcm)) // 2
    print(f"наш PCM: {len(out)} байт, ffmpeg PCM: {len(refpcm)} байт, частота={dec.sample_rate}")
    a = struct.unpack(f"<{n}h", out[:n*2])
    b = struct.unpack(f"<{n}h", refpcm[:n*2])
    diff_energy = sum((x - y) * (x - y) for x, y in zip(a, b))
    sig_energy = sum(y * y for y in b) or 1
    import math as m
    snr = 10 * m.log10(sig_energy / (diff_energy or 1))
    maxdiff = max(abs(x - y) for x, y in zip(a, b))
    print(f"SNR против ffmpeg-декода: {snr:.1f} dB, max|diff|={maxdiff}")
    ok = snr > 40
    print("VERDICT:", "OK" if ok else "FAIL")
    return 0 if ok else 1

with tempfile.TemporaryDirectory() as tmp:
    sys.exit(run(tmp))
