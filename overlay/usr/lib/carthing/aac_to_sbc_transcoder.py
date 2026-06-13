"""AAC RTP -> PCM -> SBC media payloads.

This is the isolated middle of the zero-config transcode hub. It does not own
Bluetooth channels or RTP sequence/timestamp state; a2dp_bridge will own those
when this layer is wired into live routing.
"""
from __future__ import annotations

from helix_aac_decoder import HelixAacDecoder
from sbc_encoder import SbcEncoder, SbcEncoderConfig


class AacToSbcTranscoder:
    def __init__(self, bitpool: int = 53, max_media_payload: int = 660):
        self.bitpool = bitpool
        self.max_media_payload = max_media_payload
        self.aac = HelixAacDecoder()
        self.sbc: SbcEncoder | None = None

    def close(self) -> None:
        self.aac.close()
        if self.sbc is not None:
            self.sbc.close()
            self.sbc = None

    @property
    def sample_rate(self) -> int:
        if self.sbc is not None:
            return self.sbc.config.sample_rate
        return self.aac.sample_rate or 44100

    def _ensure_sbc(self, sample_rate: int, channels: int) -> None:
        if (
            self.sbc is not None
            and self.sbc.config.sample_rate == sample_rate
            and self.sbc.config.channels == channels
            and self.sbc.config.bitpool == self.bitpool
        ):
            return
        if self.sbc is not None:
            self.sbc.close()
        self.sbc = SbcEncoder(
            SbcEncoderConfig(
                sample_rate=sample_rate,
                channels=channels,
                bitpool=self.bitpool,
            )
        )

    def feed_aac_rtp(self, packet: bytes) -> list[bytes]:
        decoded = self.aac.decode_rtp_latm(packet)
        if not decoded.pcm:
            return []
        self._ensure_sbc(decoded.sample_rate, decoded.channels)
        assert self.sbc is not None
        frames = self.sbc.encode_pcm(decoded.pcm)
        return self._pack_sbc_media_payloads(frames)

    def _pack_sbc_media_payloads(self, frames: list[bytes]) -> list[bytes]:
        payloads: list[bytes] = []
        batch: list[bytes] = []
        size = 1
        for frame in frames:
            if batch and (len(batch) >= 15 or size + len(frame) > self.max_media_payload):
                payloads.append(bytes([len(batch) & 0x0F]) + b"".join(batch))
                batch = []
                size = 1
            batch.append(frame)
            size += len(frame)
        if batch:
            payloads.append(bytes([len(batch) & 0x0F]) + b"".join(batch))
        return payloads
