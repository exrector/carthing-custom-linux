#!/usr/bin/env python3
"""Offline Helix AAC gate test.

Builds/uses a host Helix library, generates ADTS AAC with ffmpeg, decodes it
through overlay/usr/lib/carthing/helix_aac_decoder.py, and checks basic PCM
shape. This proves the decoder boundary before any live route integration.
"""
from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTHING_LIB = os.path.join(ROOT, "overlay", "usr", "lib", "carthing")
sys.path.insert(0, CARTHING_LIB)

from helix_aac_decoder import HelixAacDecoder
from bumble.codecs import AacAudioRtpPacket
from bumble.rtp import MediaPacket


def generate_pcm(path: str, seconds: int = 2, rate: int = 44100) -> None:
    with open(path, "wb") as f:
        for i in range(rate * seconds):
            t = i / rate
            left = int(9000 * math.sin(2 * math.pi * 440 * t))
            right = int(7000 * math.sin(2 * math.pi * 880 * t))
            f.write(struct.pack("<hh", left, right))


def iter_adts_frames(data: bytes):
    pos = 0
    freqs = [
        96000,
        88200,
        64000,
        48000,
        44100,
        32000,
        24000,
        22050,
        16000,
        12000,
        11025,
        8000,
        7350,
    ]
    while pos + 7 <= len(data):
        header = data[pos : pos + 7]
        if header[0] != 0xFF or (header[1] & 0xF0) != 0xF0:
            raise ValueError("invalid ADTS sync at %d" % pos)
        sf_index = (header[2] >> 2) & 0x0F
        channels = ((header[2] & 0x01) << 2) | (header[3] >> 6)
        frame_len = ((header[3] & 0x03) << 11) | (header[4] << 3) | (header[5] >> 5)
        payload_start = pos + 7
        payload_end = pos + frame_len
        yield freqs[sf_index], channels, data[payload_start:payload_end]
        pos = payload_end


def main() -> int:
    host_lib = os.environ.get("CARTHING_HELIX_AAC_LIB", "/tmp/libhelixaac-host.dylib")
    subprocess.run(
        [os.path.join(ROOT, "native", "libhelix-aac", "build.sh"), "host", host_lib],
        check=True,
    )
    os.environ["CARTHING_HELIX_AAC_LIB"] = host_lib

    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "tone.raw")
        aac = os.path.join(tmp, "tone.aac")
        generate_pcm(raw)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-i",
                raw,
                "-c:a",
                "aac",
                "-profile:a",
                "aac_low",
                "-b:a",
                "128k",
                "-f",
                "adts",
                aac,
            ],
            check=True,
        )
        data = open(aac, "rb").read()
        dec = HelixAacDecoder(host_lib)
        result = dec.decode_adts(data)
        dec.close()

        rtp_dec = HelixAacDecoder(host_lib)
        rtp_pcm = b""
        timestamp = 0
        for seq, (rate, channels, payload) in enumerate(iter_adts_frames(data)):
            latm = bytes(AacAudioRtpPacket.for_simple_aac(rate, channels, payload))
            packet = MediaPacket(2, 0, 0, 0, seq, timestamp, 0, [], 96, latm)
            rtp_pcm += rtp_dec.decode_rtp_latm(bytes(packet)).pcm
            timestamp += 1024
            if seq >= 8:
                break
        rtp_rate = rtp_dec.sample_rate
        rtp_channels = rtp_dec.channels
        rtp_dec.close()

    expected_min = 44100 * 2 * 2 * 0.8
    ok = (
        len(result.pcm) >= expected_min
        and result.sample_rate == 44100
        and result.channels == 2
        and len(rtp_pcm) > 0
        and rtp_rate == 44100
        and rtp_channels == 2
    )
    print(
        "adts=%d bytes rtp_latm=%d bytes sample_rate=%d channels=%d verdict=%s"
        % (
            len(result.pcm),
            len(rtp_pcm),
            result.sample_rate,
            result.channels,
            "OK" if ok else "FAIL",
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
