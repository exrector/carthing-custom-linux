"""Helix AAC-LC decoder wrapper.

This is the first deterministic AAC gate for the transcode hub. It is kept
separate from audio_local_sink until it passes offline and live payload tests.
Supported inputs:
  * ADTS AAC frames.
  * Full RTP packets carrying Bumble's LATM AAC payload; these are converted to
    ADTS with the vendored AacAudioRtpPacket parser before decode.
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


ERR_AAC_NONE = 0
ERR_AAC_INDATA_UNDERFLOW = -1
AAC_PROFILE_LC = 1


class AacDecodeError(RuntimeError):
    def __init__(self, code: int):
        super().__init__(f"Helix AAC decode failed: {code}")
        self.code = code


class AACFrameInfo(ctypes.Structure):
    _fields_ = [
        ("bitRate", ctypes.c_int),
        ("nChans", ctypes.c_int),
        ("sampRateCore", ctypes.c_int),
        ("sampRateOut", ctypes.c_int),
        ("bitsPerSample", ctypes.c_int),
        ("outputSamps", ctypes.c_int),
        ("profile", ctypes.c_int),
        ("tnsUsed", ctypes.c_int),
        ("pnsUsed", ctypes.c_int),
    ]


@dataclass(frozen=True)
class DecodedAac:
    pcm: bytes
    sample_rate: int
    channels: int
    samples: int


def _default_library_path() -> str:
    candidates = [
        os.environ.get("CARTHING_HELIX_AAC_LIB", ""),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "libhelixaac.so"),
        "/usr/lib/carthing/libhelixaac.so",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError("libhelixaac.so not found; set CARTHING_HELIX_AAC_LIB")


class HelixAacDecoder:
    def __init__(self, library_path: str | None = None):
        self.library_path = library_path or _default_library_path()
        self.lib = ctypes.CDLL(self.library_path)
        self.lib.AACInitDecoder.restype = ctypes.c_void_p
        self.lib.AACFreeDecoder.argtypes = [ctypes.c_void_p]
        self.lib.AACDecode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_short),
        ]
        self.lib.AACDecode.restype = ctypes.c_int
        self.lib.AACGetLastFrameInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(AACFrameInfo)]
        self.lib.AACSetRawBlockParams.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(AACFrameInfo),
        ]
        self.lib.AACSetRawBlockParams.restype = ctypes.c_int
        self.handle = self.lib.AACInitDecoder()
        if not self.handle:
            raise RuntimeError("AACInitDecoder returned NULL")
        self._pending = bytearray()
        self.sample_rate = 0
        self.channels = 0

    def close(self) -> None:
        handle = getattr(self, "handle", None)
        if handle:
            self.lib.AACFreeDecoder(handle)
            self.handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def configure_raw(self, channels: int, sample_rate: int, profile: int = AAC_PROFILE_LC) -> None:
        info = AACFrameInfo()
        info.nChans = channels
        info.sampRateCore = sample_rate
        info.profile = profile
        err = self.lib.AACSetRawBlockParams(self.handle, 0, ctypes.byref(info))
        if err != ERR_AAC_NONE:
            raise AacDecodeError(err)
        self.channels = channels
        self.sample_rate = sample_rate

    def decode_adts(self, data: bytes) -> DecodedAac:
        self._pending.extend(data)
        return self._decode_pending()

    def decode_raw_block(self, data: bytes) -> DecodedAac:
        self._pending.extend(data)
        return self._decode_pending()

    def decode_rtp_latm(self, packet: bytes) -> DecodedAac:
        from bumble.codecs import AacAudioRtpPacket
        from bumble.rtp import MediaPacket

        media = MediaPacket.from_bytes(packet)
        adts = AacAudioRtpPacket.from_bytes(media.payload).to_adts()
        return self.decode_adts(adts)

    def _decode_pending(self) -> DecodedAac:
        if not self._pending:
            return DecodedAac(b"", self.sample_rate, self.channels, 0)

        backing = ctypes.create_string_buffer(bytes(self._pending), len(self._pending))
        start_addr = ctypes.addressof(backing)
        inbuf = ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte))
        inbuf_p = ctypes.pointer(inbuf)
        bytes_left = ctypes.c_int(len(self._pending))
        outbuf = (ctypes.c_short * (8192 * 2))()
        chunks: list[bytes] = []

        while bytes_left.value > 0:
            before_left = bytes_left.value
            err = self.lib.AACDecode(self.handle, inbuf_p, ctypes.byref(bytes_left), outbuf)
            if err == ERR_AAC_INDATA_UNDERFLOW:
                break
            if err != ERR_AAC_NONE:
                raise AacDecodeError(err)
            info = AACFrameInfo()
            self.lib.AACGetLastFrameInfo(self.handle, ctypes.byref(info))
            self.sample_rate = int(info.sampRateOut or info.sampRateCore or self.sample_rate)
            self.channels = int(info.nChans or self.channels)
            samples = int(info.outputSamps)
            chunks.append(ctypes.string_at(outbuf, samples * ctypes.sizeof(ctypes.c_short)))
            if bytes_left.value == before_left:
                break

        consumed = ctypes.addressof(inbuf_p.contents.contents) - start_addr
        if consumed > 0:
            del self._pending[:consumed]
        pcm = b"".join(chunks)
        return DecodedAac(pcm, self.sample_rate, self.channels, len(pcm) // 2)
