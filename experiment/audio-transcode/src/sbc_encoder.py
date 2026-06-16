"""Native SBC encoder wrapper for the transcode hub."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


SBC_FREQ = {16000: 0, 32000: 1, 44100: 2, 48000: 3}
SBC_BLK_16 = 3
SBC_MODE_MONO = 0
SBC_MODE_JOINT_STEREO = 3
SBC_AM_LOUDNESS = 0
SBC_SB_8 = 1
SBC_LE = 0


class SbcEncodeError(RuntimeError):
    pass


class SbcT(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_ulong),
        ("frequency", ctypes.c_uint8),
        ("blocks", ctypes.c_uint8),
        ("subbands", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
        ("allocation", ctypes.c_uint8),
        ("bitpool", ctypes.c_uint8),
        ("endian", ctypes.c_uint8),
        ("priv", ctypes.c_void_p),
        ("priv_alloc_base", ctypes.c_void_p),
    ]


@dataclass(frozen=True)
class SbcEncoderConfig:
    sample_rate: int = 44100
    channels: int = 2
    bitpool: int = 53


def _default_library_path() -> str:
    candidates = [
        os.environ.get("CARTHING_SBC_LIB", ""),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "libsbc.so"),
        "/usr/lib/carthing/libsbc.so",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError("libsbc.so not found; set CARTHING_SBC_LIB")


class SbcEncoder:
    def __init__(self, config: SbcEncoderConfig, library_path: str | None = None):
        if config.sample_rate not in SBC_FREQ:
            raise ValueError(f"unsupported SBC sample rate: {config.sample_rate}")
        if config.channels not in (1, 2):
            raise ValueError(f"unsupported SBC channels: {config.channels}")
        self.config = config
        self.library_path = library_path or _default_library_path()
        self.lib = ctypes.CDLL(self.library_path)
        self.lib.sbc_init.argtypes = [ctypes.POINTER(SbcT), ctypes.c_ulong]
        self.lib.sbc_init.restype = ctypes.c_int
        self.lib.sbc_finish.argtypes = [ctypes.POINTER(SbcT)]
        self.lib.sbc_get_codesize.argtypes = [ctypes.POINTER(SbcT)]
        self.lib.sbc_get_codesize.restype = ctypes.c_size_t
        self.lib.sbc_get_frame_length.argtypes = [ctypes.POINTER(SbcT)]
        self.lib.sbc_get_frame_length.restype = ctypes.c_size_t
        self.lib.sbc_encode.argtypes = [
            ctypes.POINTER(SbcT),
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_ssize_t),
        ]
        self.lib.sbc_encode.restype = ctypes.c_ssize_t
        self.state = SbcT()
        err = self.lib.sbc_init(ctypes.byref(self.state), 0)
        if err:
            raise SbcEncodeError(f"sbc_init failed: {err}")
        self.state.frequency = SBC_FREQ[config.sample_rate]
        self.state.blocks = SBC_BLK_16
        self.state.subbands = SBC_SB_8
        self.state.mode = SBC_MODE_MONO if config.channels == 1 else SBC_MODE_JOINT_STEREO
        self.state.allocation = SBC_AM_LOUDNESS
        self.state.bitpool = config.bitpool
        self.state.endian = SBC_LE
        self.codesize = int(self.lib.sbc_get_codesize(ctypes.byref(self.state)))
        self.frame_length = int(self.lib.sbc_get_frame_length(ctypes.byref(self.state)))
        self._pending = bytearray()

    def close(self) -> None:
        state = getattr(self, "state", None)
        if state is not None:
            self.lib.sbc_finish(ctypes.byref(state))
            self.state = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def encode_pcm(self, pcm: bytes) -> list[bytes]:
        self._pending.extend(pcm)
        frames: list[bytes] = []
        outbuf = (ctypes.c_ubyte * max(1024, self.frame_length + 16))()
        written = ctypes.c_ssize_t()
        while len(self._pending) >= self.codesize:
            chunk = bytes(self._pending[: self.codesize])
            inbuf = ctypes.create_string_buffer(chunk, len(chunk))
            consumed = self.lib.sbc_encode(
                ctypes.byref(self.state),
                inbuf,
                len(chunk),
                outbuf,
                len(outbuf),
                ctypes.byref(written),
            )
            if consumed <= 0:
                raise SbcEncodeError(f"sbc_encode failed: {consumed}")
            frames.append(bytes(outbuf[: written.value]))
            del self._pending[:consumed]
        return frames
