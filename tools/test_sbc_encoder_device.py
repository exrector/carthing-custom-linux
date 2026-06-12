# Тест эталонного энкодера libsbc на устройстве: PCM-тон -> SBC -> наш декодер -> сверка
import ctypes, math, struct, sys, time
sys.path.insert(0, "/usr/lib/carthing")

class SbcT(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_ulong),
                ("frequency", ctypes.c_uint8), ("blocks", ctypes.c_uint8),
                ("subbands", ctypes.c_uint8), ("mode", ctypes.c_uint8),
                ("allocation", ctypes.c_uint8), ("bitpool", ctypes.c_uint8),
                ("endian", ctypes.c_uint8),
                ("priv", ctypes.c_void_p), ("priv_alloc_base", ctypes.c_void_p)]

lib = ctypes.CDLL("/usr/lib/carthing/libsbc.so")
lib.sbc_encode.restype = ctypes.c_ssize_t
lib.sbc_encode.argtypes = [ctypes.POINTER(SbcT), ctypes.c_void_p, ctypes.c_size_t,
                           ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ssize_t)]
lib.sbc_get_codesize.restype = ctypes.c_size_t
lib.sbc_get_frame_length.restype = ctypes.c_size_t

s = SbcT()
assert lib.sbc_init(ctypes.byref(s), 0) == 0
s.frequency = 2      # 44100
s.blocks = 3         # 16
s.subbands = 1       # 8
s.mode = 3           # joint stereo
s.allocation = 0     # loudness
s.bitpool = 53
s.endian = 0         # LE
codesize = lib.sbc_get_codesize(ctypes.byref(s))
framelen = lib.sbc_get_frame_length(ctypes.byref(s))
print("codesize=%d framelen=%d" % (codesize, framelen))

# 1с стерео тона
pcm = bytearray()
for i in range(44100):
    v = int(11000 * math.sin(2 * math.pi * 440 * i / 44100.0))
    pcm += struct.pack("<hh", v, v)
enc = bytearray()
outbuf = (ctypes.c_char * 1024)()
written = ctypes.c_ssize_t()
t0 = time.monotonic()
pos = 0
while pos + codesize <= len(pcm):
    n = lib.sbc_encode(ctypes.byref(s), bytes(pcm[pos:pos+codesize]), codesize,
                       outbuf, 1024, ctypes.byref(written))
    if n <= 0:
        print("encode err", n); sys.exit(1)
    enc += outbuf[:written.value]
    pos += n
dt = time.monotonic() - t0
print("encoded 1.00s in %.2fs -> x%.1f realtime, %d bytes" % (dt, 1.0/dt, len(enc)))

from sbc_decoder import SbcDecoder
dec = SbcDecoder()
out = dec.decode("sbc-raw", bytes(enc))
n = min(len(out), len(pcm)) // 2
a = struct.unpack("<%dh" % n, out[:n*2])
b = struct.unpack("<%dh" % n, bytes(pcm[:n*2]))
# выравнивание задержки фильтра: ищем лучший сдвиг по корреляции на сетке
best = None
for shift in range(0, 1024, 2):
    diff = sum(abs(a[i+shift] - b[i]) for i in range(0, 20000, 7))
    if best is None or diff < best[1]:
        best = (shift, diff)
shift = best[0]
err = sum(abs(a[i+shift] - b[i]) for i in range(0, 30000)) / 30000
print("delay=%d samples, mean|err|=%.1f (из 32768)" % (shift, err))
print("VERDICT:", "OK" if err < 200 else "FAIL")
