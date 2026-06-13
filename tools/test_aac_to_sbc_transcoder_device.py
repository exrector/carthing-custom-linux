#!/usr/bin/env python3
"""Device-side smoke for AAC RTP -> SBC media payloads.

Run on Car Thing after deploying:
  PYTHONPATH=/usr/lib/carthing:/usr/lib/carthing/vendor \
    python3 /tmp/test_aac_to_sbc_transcoder_device.py /tmp/input.rtp
"""
from __future__ import annotations

import sys

from aac_to_sbc_transcoder import AacToSbcTranscoder
from sbc_decoder import SbcDecoder


def main() -> int:
    packet_path = sys.argv[1]
    packet = open(packet_path, "rb").read()
    transcoder = AacToSbcTranscoder()
    payloads = transcoder.feed_aac_rtp(packet)
    transcoder.close()
    if not payloads:
        print("FAIL: no SBC payloads")
        return 1

    raw_frames = b""
    frame_count = 0
    for payload in payloads:
        count = payload[0] & 0x0F
        frame_count += count
        raw_frames += payload[1:]

    decoder = SbcDecoder()
    pcm = decoder.decode("sbc-raw", raw_frames)
    ok = frame_count > 0 and len(pcm) > 0 and decoder.sample_rate == 44100
    print(
        "payloads=%d frames=%d sbc_bytes=%d pcm_bytes=%d sample_rate=%d verdict=%s"
        % (
            len(payloads),
            frame_count,
            len(raw_frames),
            len(pcm),
            decoder.sample_rate,
            "OK" if ok else "FAIL",
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
