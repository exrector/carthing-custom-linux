"""Программный SBC-декодер (этаж 3 «работы над чипом») — чистый Python.

ЗАЧЕМ SBC, а не AAC: для маршрута line-out мост объявляет iPhone «SBC-only»
(механизм перепереговоров кодека уже есть — ensure_source_codec_matches_route,
сделан Codex 2026-06-11 для Maedhawk) -> iPhone шлёт SBC -> декодируем здесь ->
PCM -> T9015. AAC в чистом Python нереален; SBC — спроектирован «low-complexity».

ИСТОЧНИК АЛГОРИТМА: транскрипция референсной bluez libsbc (sbc.c, sbc_math.h,
sbc_tables.h; LGPL-2.1+; A2DP spec Appendix B). Таблицы СГЕНЕРИРОВАНЫ из
исходника автоматически (масштабирование SS/SN уже применено) — не редактировать
руками. Fixed-point идентичен bluez (default-точность: FIXED_T int16), Python-инты
не переполняются — поведение совпадает с C на корректных потоках.

ПРОИЗВОДИТЕЛЬНОСТЬ: декодер живёт в sink-ПРОЦЕССЕ (audio_local_sink serve) на
своём ядре A53 — GIL рантайма не трогает. Замер на устройстве см. в протоколе.

ПРОВЕРЕНО против ffmpeg (эталонный кодек SBC): см. tools/test_sbc_decoder.py.

[CLAUDE 2026-06-12]
"""
from __future__ import annotations

import struct

# АВТОГЕНЕРИРОВАНО из bluez sbc_tables.h/sbc.c (LGPL-2.1+, A2DP Appendix B).
# Масштабирование применено: proto: SS4>>12/SS8>>14; synmatrix: SN>>14.
OFFSET4 = [[-1, 0, 0, 0], [-2, 0, 0, 1], [-2, 0, 0, 1], [-2, 0, 0, 1]]
OFFSET8 = [[-2, 0, 0, 0, 0, 0, 0, 1], [-3, 0, 0, 0, 0, 0, 1, 2], [-4, 0, 0, 0, 0, 0, 1, 2], [-4, 0, 0, 0, 0, 0, 1, 2]]
PROTO_4_40M0 = [0, -1431, -17773, 17772, 1430, -71, -2679, -25558, 10177, 401, -196, -3785, -32328, 3777, -245, -359, -4220, -36940, -804, -511]
PROTO_4_40M1 = [-503, -3392, -38577, -3392, -503, -511, -804, -36940, -4220, -359, -245, 3777, -32328, -3785, -196, 401, 10177, -25558, -2679, -71]
PROTO_8_80M0 = [0, -1484, -17826, 17825, 1483, -42, -2105, -21754, 13942, 916, -90, -2742, -25579, 10243, 432, -146, -3342, -29150, 6844, 46, -216, -3842, -32314, 3837, -237, -299, -4170, -34935, 1288, -424, -388, -4253, -36898, -767, -523, -468, -4016, -38114, -2322, -552]
PROTO_8_80M1 = [-528, -3392, -38524, -3392, -528, -552, -2322, -38114, -4016, -468, -523, -767, -36898, -4253, -388, -424, 1288, -34935, -4170, -299, -237, 3837, -32314, -3842, -216, 46, 6844, -29150, -3342, -146, 432, 10243, -25579, -2742, -90, 916, 13942, -21754, -2105, -42]
SYNMATRIX4 = [[5792, -5793, -5793, 5792], [3134, -7569, 7568, -3135], [0, 0, 0, 0], [-3135, 7568, -7569, 3134], [-5793, 5792, 5792, -5793], [-7569, -3135, 3134, 7568], [-8192, -8192, -8192, -8192], [-7569, -3135, 3134, 7568]]
SYNMATRIX8 = [[5792, -5793, -5793, 5792, 5792, -5793, -5793, 5792], [4551, -8035, 1598, 6811, -6812, -1599, 8034, -4552], [3134, -7569, 7568, -3135, -3135, 7568, -7569, 3134], [1598, -4552, 6811, -8035, 8034, -6812, 4551, -1599], [0, 0, 0, 0, 0, 0, 0, 0], [-1599, 4551, -6812, 8034, -8035, 6811, -4552, 1598], [-3135, 7568, -7569, 3134, 3134, -7569, 7568, -3135], [-4552, 8034, -1599, -6812, 6811, 1598, -8035, 4551], [-5793, 5792, 5792, -5793, -5793, 5792, 5792, -5793], [-6812, 1598, 8034, 4551, -4552, -8035, -1599, 6811], [-7569, -3135, 3134, 7568, 7568, 3134, -3135, -7569], [-8035, -6812, -4552, -1599, 1598, 4551, 6811, 8034], [-8192, -8192, -8192, -8192, -8192, -8192, -8192, -8192], [-8035, -6812, -4552, -1599, 1598, 4551, 6811, 8034], [-7569, -3135, 3134, 7568, 7568, 3134, -3135, -7569], [-6812, 1598, 8034, 4551, -4552, -8035, -1599, 6811]]
CRC_TABLE = [0, 29, 58, 39, 116, 105, 78, 83, 232, 245, 210, 207, 156, 129, 166, 187, 205, 208, 247, 234, 185, 164, 131, 158, 37, 56, 31, 2, 81, 76, 107, 118, 135, 154, 189, 160, 243, 238, 201, 212, 111, 114, 85, 72, 27, 6, 33, 60, 74, 87, 112, 109, 62, 35, 4, 25, 162, 191, 152, 133, 214, 203, 236, 241, 19, 14, 41, 52, 103, 122, 93, 64, 251, 230, 193, 220, 143, 146, 181, 168, 222, 195, 228, 249, 170, 183, 144, 141, 54, 43, 12, 17, 66, 95, 120, 101, 148, 137, 174, 179, 224, 253, 218, 199, 124, 97, 70, 91, 8, 21, 50, 47, 89, 68, 99, 126, 45, 48, 23, 10, 177, 172, 139, 150, 197, 216, 255, 226, 38, 59, 28, 1, 82, 79, 104, 117, 206, 211, 244, 233, 186, 167, 128, 157, 235, 246, 209, 204, 159, 130, 165, 184, 3, 30, 57, 36, 119, 106, 77, 80, 161, 188, 155, 134, 213, 200, 239, 242, 73, 84, 115, 110, 61, 32, 7, 26, 108, 113, 86, 75, 24, 5, 34, 63, 132, 153, 190, 163, 240, 237, 202, 215, 53, 40, 15, 18, 65, 92, 123, 102, 221, 192, 231, 250, 169, 180, 147, 142, 248, 229, 194, 223, 140, 145, 182, 171, 16, 13, 42, 55, 100, 121, 94, 67, 178, 175, 136, 149, 198, 219, 252, 225, 90, 71, 96, 125, 46, 51, 20, 9, 127, 98, 69, 88, 11, 22, 49, 44, 151, 138, 173, 176, 227, 254, 217, 196]


_FREQS = (16000, 32000, 44100, 48000)

# ── C-ускоритель синтеза (sbc_synth.so, кросс-сборка на Mac, см. native/) ─────
# Python-синтез остаётся ФОЛБЭКОМ (медленный, 0.5x rt) — поведение бит-в-бит.
import ctypes as _ct
import os as _os

_SYNTH_LIB = None
try:
    _SYNTH_LIB = _ct.CDLL(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "sbc_synth.so"))
except Exception:
    _SYNTH_LIB = None

def _flat_i32(rows):
    flat = [x for r in rows for x in r] if isinstance(rows[0], list) else list(rows)
    return (_ct.c_int32 * len(flat))(*flat)

if _SYNTH_LIB is not None:
    _C_SYN8 = _flat_i32(SYNMATRIX8)
    _C_M0_8 = _flat_i32(PROTO_8_80M0)
    _C_M1_8 = _flat_i32(PROTO_8_80M1)
    _C_SYN4 = _flat_i32(SYNMATRIX4)
    _C_M0_4 = _flat_i32(PROTO_4_40M0)
    _C_M1_4 = _flat_i32(PROTO_4_40M1)
_FIXED_EXTRA_BITS = 2          # SBCDEC_FIXED_EXTRA_BITS
_MONO, _DUAL, _STEREO, _JOINT = 0, 1, 2, 3


def _crc8(data: bytes, bit_len: int) -> int:
    crc = 0x0F
    octets = bit_len >> 3
    for i in range(octets):
        crc = CRC_TABLE[crc ^ data[i]]
    rem = bit_len & 7
    if rem:
        octet = data[octets]
        for bit in range(rem):
            crc = ((crc << 1) ^ (0x1D if ((crc >> 7) ^ ((octet >> (7 - bit)) & 1)) else 0)) & 0xFF
    return crc


def _calc_bits(mode, channels, subbands, frequency, allocation, scale_factor, bitpool):
    """Транскрипция sbc_calculate_bits (bluez). Возвращает bits[2][8]."""
    bits = [[0] * 8 for _ in range(2)]
    offsets = OFFSET4 if subbands == 4 else OFFSET8
    if mode in (_MONO, _DUAL):
        for ch in range(channels):
            bitneed = [0] * subbands
            max_bitneed = 0
            if allocation == 1:  # SNR
                for sb in range(subbands):
                    bitneed[sb] = scale_factor[ch][sb]
                    max_bitneed = max(max_bitneed, bitneed[sb])
            else:                # LOUDNESS
                for sb in range(subbands):
                    if scale_factor[ch][sb] == 0:
                        bitneed[sb] = -5
                    else:
                        loudness = scale_factor[ch][sb] - offsets[frequency][sb]
                        # C: отрицательное /2 округляется К НУЛЮ; в Python // — к -inf.
                        bitneed[sb] = loudness // 2 if loudness > 0 else loudness
                    max_bitneed = max(max_bitneed, bitneed[sb])
            bitcount = 0
            slicecount = 0
            bitslice = max_bitneed + 1
            while True:
                bitslice -= 1
                bitcount += slicecount
                slicecount = 0
                for sb in range(subbands):
                    bn = bitneed[sb]
                    if bitslice + 1 < bn < bitslice + 16:
                        slicecount += 1
                    elif bn == bitslice + 1:
                        slicecount += 2
                if bitcount + slicecount >= bitpool:
                    break
            if bitcount + slicecount == bitpool:
                bitcount += slicecount
                bitslice -= 1
            for sb in range(subbands):
                bits[ch][sb] = 0 if bitneed[sb] < bitslice + 2 else min(bitneed[sb] - bitslice, 16)
            sb = 0
            while bitcount < bitpool and sb < subbands:
                if 2 <= bits[ch][sb] < 16:
                    bits[ch][sb] += 1
                    bitcount += 1
                elif bitneed[sb] == bitslice + 1 and bitpool > bitcount + 1:
                    bits[ch][sb] = 2
                    bitcount += 2
                sb += 1
            sb = 0
            while bitcount < bitpool and sb < subbands:
                if bits[ch][sb] < 16:
                    bits[ch][sb] += 1
                    bitcount += 1
                sb += 1
    else:  # STEREO / JOINT — общий bitpool на оба канала
        bitneed = [[0] * subbands for _ in range(2)]
        max_bitneed = 0
        if allocation == 1:
            for ch in range(2):
                for sb in range(subbands):
                    bitneed[ch][sb] = scale_factor[ch][sb]
                    max_bitneed = max(max_bitneed, bitneed[ch][sb])
        else:
            for ch in range(2):
                for sb in range(subbands):
                    if scale_factor[ch][sb] == 0:
                        bitneed[ch][sb] = -5
                    else:
                        loudness = scale_factor[ch][sb] - offsets[frequency][sb]
                        bitneed[ch][sb] = loudness // 2 if loudness > 0 else loudness
                    max_bitneed = max(max_bitneed, bitneed[ch][sb])
        bitcount = 0
        slicecount = 0
        bitslice = max_bitneed + 1
        while True:
            bitslice -= 1
            bitcount += slicecount
            slicecount = 0
            for ch in range(2):
                for sb in range(subbands):
                    bn = bitneed[ch][sb]
                    if bitslice + 1 < bn < bitslice + 16:
                        slicecount += 1
                    elif bn == bitslice + 1:
                        slicecount += 2
            if bitcount + slicecount >= bitpool:
                break
        if bitcount + slicecount == bitpool:
            bitcount += slicecount
            bitslice -= 1
        for ch in range(2):
            for sb in range(subbands):
                bits[ch][sb] = 0 if bitneed[ch][sb] < bitslice + 2 else min(bitneed[ch][sb] - bitslice, 16)
        ch = sb = 0
        while bitcount < bitpool and sb < subbands:
            if 2 <= bits[ch][sb] < 16:
                bits[ch][sb] += 1
                bitcount += 1
            elif bitneed[ch][sb] == bitslice + 1 and bitpool > bitcount + 1:
                bits[ch][sb] = 2
                bitcount += 2
            if ch == 1:
                ch = 0
                sb += 1
            else:
                ch = 1
        ch = sb = 0
        while bitcount < bitpool and sb < subbands:
            if bits[ch][sb] < 16:
                bits[ch][sb] += 1
                bitcount += 1
            if ch == 1:
                ch = 0
                sb += 1
            else:
                ch = 1
    return bits


class SbcFrameDecoder:
    """Состояние синтеза (V-буферы) живёт между кадрами — один экземпляр на поток."""

    def __init__(self):
        self.v = [[0] * 170, [0] * 170]
        self.offset = None
        self.sample_rate = 44100
        self.channels = 2
        if _SYNTH_LIB is not None:
            self.c_v = [(_ct.c_int32 * 170)(), (_ct.c_int32 * 170)()]
            self.c_off = [(_ct.c_int32 * 16)(), (_ct.c_int32 * 16)()]
            self.c_sb = (_ct.c_int32 * (16 * 8))()
            self.c_out = (_ct.c_int16 * (16 * 8))()

    def decode_frame(self, data: bytes, pos: int, out: bytearray):
        """Декодирует ОДИН кадр с data[pos:]; возвращает новую позицию.
        PCM (interleaved S16LE стерео — моно дублируется) дописывается в out."""
        if pos + 4 > len(data) or data[pos] != 0x9C:
            raise ValueError("bad syncword")
        h1 = data[pos + 1]
        frequency = (h1 >> 6) & 3
        blocks = ((h1 >> 4) & 3) * 4 + 4
        mode = (h1 >> 2) & 3
        channels = 1 if mode == _MONO else 2
        allocation = (h1 >> 1) & 1
        subbands = 8 if (h1 & 1) else 4
        bitpool = data[pos + 2]
        self.sample_rate = _FREQS[frequency]
        self.channels = channels

        if self.offset is None:
            self.offset = [[10 * i + 10 for i in range(subbands * 2)] for _ in range(2)]
            if _SYNTH_LIB is not None:
                for ch in range(2):
                    for i in range(subbands * 2):
                        self.c_off[ch][i] = 10 * i + 10

        consumed = 32                      # биты, от начала кадра
        crc_header = bytearray(11)
        crc_header[0] = h1
        crc_header[1] = bitpool
        crc_pos = 16
        joint = 0
        base = pos
        if mode == _JOINT:
            d4 = data[base + 4]
            for sb in range(subbands - 1):
                joint |= ((d4 >> (7 - sb)) & 1) << sb
            crc_header[2] = d4 & 0xF0 if subbands == 4 else d4
            consumed += subbands
            crc_pos += subbands

        scale_factor = [[0] * 8, [0] * 8]
        for ch in range(channels):
            for sb in range(subbands):
                b = base + (consumed >> 3)
                sf = (data[b] >> (4 - (consumed & 7))) & 0x0F
                scale_factor[ch][sb] = sf
                crc_header[crc_pos >> 3] |= sf << (4 - (crc_pos & 7))
                consumed += 4
                crc_pos += 4

        if data[base + 3] != _crc8(bytes(crc_header), crc_pos):
            raise ValueError("bad CRC")

        bits = _calc_bits(mode, channels, subbands, frequency, allocation, scale_factor, bitpool)
        levels = [[(1 << bits[ch][sb]) - 1 for sb in range(8)] for ch in range(2)]

        # деквантизация: окно кадра -> ОДИН big-int, поля битов — сдвигами
        # (битовый цикл по одному биту был 37% всего времени декода)
        window = data[base:base + 600]
        big = int.from_bytes(window, "big")
        wbits = len(window) * 8
        sb_sample = [[[0] * 8 for _ in range(2)] for _ in range(blocks)]
        for blk in range(blocks):
            for ch in range(channels):
                row = sb_sample[blk][ch]
                for sb in range(subbands):
                    lvl = levels[ch][sb]
                    if lvl == 0:
                        continue
                    nbits = bits[ch][sb]
                    audio_sample = (big >> (wbits - consumed - nbits)) & ((1 << nbits) - 1)
                    consumed += nbits
                    shift = scale_factor[ch][sb] + 1 + _FIXED_EXTRA_BITS
                    row[sb] = ((((audio_sample << 1) | 1) << shift) // lvl) - (1 << shift)

        if mode == _JOINT:
            for blk in range(blocks):
                row = sb_sample[blk]
                for sb in range(subbands):
                    if joint & (1 << sb):
                        t = row[0][sb] + row[1][sb]
                        row[1][sb] = row[0][sb] - row[1][sb]
                        row[0][sb] = t

        # синтез: C-ускоритель (десятки x) либо Python-фолбэк (бит-в-бит)
        if _SYNTH_LIB is not None:
            pcm = []
            fn = _SYNTH_LIB.sbc_synth8 if subbands == 8 else _SYNTH_LIB.sbc_synth4
            syn, m0, m1 = ((_C_SYN8, _C_M0_8, _C_M1_8) if subbands == 8
                           else (_C_SYN4, _C_M0_4, _C_M1_4))
            for ch in range(channels):
                csb = self.c_sb
                k = 0
                for blk in range(blocks):
                    row = sb_sample[blk][ch]
                    for sb in range(subbands):
                        csb[k] = row[sb]
                        k += 1
                fn(self.c_v[ch], self.c_off[ch], csb, blocks, syn, m0, m1, self.c_out)
                n = blocks * subbands
                pcm.append(self.c_out[:n])
        else:
            pcm = [self._synth8(ch, sb_sample, blocks) if subbands == 8
                   else self._synth4(ch, sb_sample, blocks)
                   for ch in range(channels)]

        if channels == 2:
            l, r = pcm
            inter = [0] * (2 * len(l))
            inter[0::2] = l
            inter[1::2] = r
        else:
            m = pcm[0]
            inter = [0] * (2 * len(m))
            inter[0::2] = m
            inter[1::2] = m
        out += struct.pack("<%dh" % len(inter), *inter)

        if consumed & 7:
            consumed += 8 - (consumed & 7)
        return pos + (consumed >> 3)

    def _synth8(self, ch, sb_sample, blocks):
        v = self.v[ch]
        offset = self.offset[ch]
        syn = SYNMATRIX8
        m0 = PROTO_8_80M0
        m1 = PROTO_8_80M1
        out = []
        clip = self._clip16
        for blk in range(blocks):
            s = sb_sample[blk][ch]
            s0, s1, s2, s3, s4, s5, s6, s7 = s
            for i in range(16):
                off = offset[i] - 1
                if off < 0:
                    off = 159
                    v[160:169] = v[0:9]
                offset[i] = off
                row = syn[i]
                v[off] = (row[0] * s0 + row[1] * s1 + row[2] * s2 + row[3] * s3 +
                          row[4] * s4 + row[5] * s5 + row[6] * s6 + row[7] * s7) >> 15
            for i in range(8):
                oi = offset[i]
                ok = offset[(i + 8) & 0xF]
                idx = i * 5
                out.append(clip((v[oi] * m0[idx] + v[ok + 1] * m1[idx] +
                                 v[oi + 2] * m0[idx + 1] + v[ok + 3] * m1[idx + 1] +
                                 v[oi + 4] * m0[idx + 2] + v[ok + 5] * m1[idx + 2] +
                                 v[oi + 6] * m0[idx + 3] + v[ok + 7] * m1[idx + 3] +
                                 v[oi + 8] * m0[idx + 4] + v[ok + 9] * m1[idx + 4]) >> 15))
        return out

    def _synth4(self, ch, sb_sample, blocks):
        v = self.v[ch]
        offset = self.offset[ch]
        syn = SYNMATRIX4
        m0 = PROTO_4_40M0
        m1 = PROTO_4_40M1
        out = []
        clip = self._clip16
        for blk in range(blocks):
            s = sb_sample[blk][ch]
            for i in range(8):
                off = offset[i] - 1
                if off < 0:
                    off = 79
                    v[80:89] = v[0:9]
                offset[i] = off
                row = syn[i]
                v[off] = (row[0] * s[0] + row[1] * s[1] + row[2] * s[2] + row[3] * s[3]) >> 15
            for i in range(4):
                oi = offset[i]
                ok = offset[(i + 4) & 0xF]
                idx = i * 5
                out.append(clip((v[oi] * m0[idx] + v[ok + 1] * m1[idx] +
                                 v[oi + 2] * m0[idx + 1] + v[ok + 3] * m1[idx + 1] +
                                 v[oi + 4] * m0[idx + 2] + v[ok + 5] * m1[idx + 2] +
                                 v[oi + 6] * m0[idx + 3] + v[ok + 7] * m1[idx + 3] +
                                 v[oi + 8] * m0[idx + 4] + v[ok + 9] * m1[idx + 4]) >> 15))
        return out

    @staticmethod
    def _clip16(s):
        if s > 0x7FFF:
            return 0x7FFF
        if s < -0x8000:
            return -0x8000
        return s


class SbcDecoder:
    """AudioDecoder для audio_local_sink: вход = A2DP RTP payload
    (1 байт media-header: [F|S|L|число кадров] + SBC-кадры подряд),
    либо codec=="sbc-raw" = голые кадры без media-header (тесты/дампы)."""

    def __init__(self):
        self._frame = SbcFrameDecoder()

    @property
    def sample_rate(self):
        return self._frame.sample_rate

    def decode(self, codec: str, payload: bytes) -> bytes:
        if codec == "sbc":
            data = payload[1:]      # A2DP media-payload header (фрагментацию не поддерживаем)
        elif codec == "sbc-raw":
            data = payload
        else:
            raise ValueError(f"SbcDecoder не умеет {codec}")
        out = bytearray()
        pos = 0
        while pos + 4 <= len(data) and data[pos] == 0x9C:
            pos = self._frame.decode_frame(data, pos, out)
        return bytes(out)
