"""
Amlogic GE2D hardware 2D accelerator — pure-Python ctypes wrapper.
Target: Linux 4.9 aarch64, /dev/ge2d (char 237:0), Car Thing (S905D2).

Buffer lifecycle:
    dev = GE2DDevice()
    buf = dev.alloc(width, height, fmt=GE2D_FMT_RGBA)  # DMA buffer
    buf.pixels[0:4] = b'\xff\x00\x00\xff'              # CPU write
    dev.fillrect(buf, color=0xFF0000FF, x=0, y=0, w=100, h=100)  # RGBA red
    dev.blit(src=buf_a, dst=buf_b, sx=0, sy=0, sw=480, sh=800, dx=0, dy=0)
    buf.close()
    dev.close()

Formats (pixel_format_t from ge2d_port.h):
    GE2D_FMT_RGBA = 1    RGBA_8888  32 bpp  (PIL 'RGBA')
    GE2D_FMT_RGB  = 3    RGB_888    24 bpp  (PIL 'RGB')
    GE2D_FMT_RGB565 = 4  RGB_565    16 bpp  (framebuffer native)
    GE2D_FMT_BGRA = 5    BGRA_8888  32 bpp
"""

import ctypes
import ctypes.util
import mmap
import os

# ---------------------------------------------------------------------------
# libc ioctl binding
# ---------------------------------------------------------------------------

_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_libc.ioctl.restype  = ctypes.c_int
_libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]

def _ioctl(fd, code, struct):
    ret = _libc.ioctl(fd, code, ctypes.byref(struct))
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"ioctl({hex(code)}) failed: {os.strerror(errno)}")
    return ret

# ---------------------------------------------------------------------------
# ioctl code helpers (Linux ARM64 / LP64)
# ---------------------------------------------------------------------------

_IOC_WRITE   = 1
_IOC_READ    = 2
_DIRSHIFT    = 30
_SIZESHIFT   = 16
_TYPESHIFT   = 8
_NRSHIFT     = 0

def _IOW(t, n, size):
    return (_IOC_WRITE << _DIRSHIFT) | (size << _SIZESHIFT) | (t << _TYPESHIFT) | n

def _IOR(t, n, size):
    return (_IOC_READ << _DIRSHIFT) | (size << _SIZESHIFT) | (t << _TYPESHIFT) | n

_G = ord('G')

# raw op codes (old-style, no size in code — still take struct* arg)
GE2D_FILLRECTANGLE  = 0x46fd
GE2D_STRETCHBLIT    = 0x46fe
GE2D_BLIT           = 0x46ff
GE2D_BLEND          = 0x4700
GE2D_GET_CAP        = 0x470b

# ---------------------------------------------------------------------------
# ctypes structures (aarch64 LP64 layout, no custom packing)
# ---------------------------------------------------------------------------

class _SrcDstPara(ctypes.Structure):
    _fields_ = [
        ("canvas_index",   ctypes.c_int),
        ("top",            ctypes.c_int),
        ("left",           ctypes.c_int),
        ("width",          ctypes.c_int),
        ("height",         ctypes.c_int),
        ("format",         ctypes.c_int),
        ("mem_type",       ctypes.c_int),
        ("color",          ctypes.c_int),
        ("x_rev",          ctypes.c_ubyte),
        ("y_rev",          ctypes.c_ubyte),
        ("fill_color_en",  ctypes.c_ubyte),
        ("fill_mode",      ctypes.c_ubyte),
    ]   # 36 bytes

class _SrcKeyCtrl(ctypes.Structure):
    _fields_ = [
        ("key_enable", ctypes.c_int),
        ("key_color",  ctypes.c_int),
        ("key_mask",   ctypes.c_int),
        ("key_mode",   ctypes.c_int),
    ]   # 16 bytes

class _PlaneIon(ctypes.Structure):
    _fields_ = [
        ("addr",      ctypes.c_ulong),   # 8 bytes (unsigned long, aarch64)
        ("w",         ctypes.c_uint),    # 4
        ("h",         ctypes.c_uint),    # 4
        ("shared_fd", ctypes.c_int),     # 4
        ("_pad",      ctypes.c_uint),    # 4 — align to 8 for next struct
    ]   # 24 bytes

class _ConfigExIon(ctypes.Structure):
    _fields_ = [
        ("src_para",             _SrcDstPara),
        ("src2_para",            _SrcDstPara),
        ("dst_para",             _SrcDstPara),
        ("src_key",              _SrcKeyCtrl),
        ("src2_key",             _SrcKeyCtrl),
        ("src1_cmult_asel",      ctypes.c_ubyte),
        ("src2_cmult_asel",      ctypes.c_ubyte),
        ("src2_cmult_ad",        ctypes.c_ubyte),
        ("_pad0",                ctypes.c_ubyte),
        ("alu_const_color",      ctypes.c_int),
        ("src1_gb_alpha_en",     ctypes.c_ubyte),
        ("_pad1",                ctypes.c_ubyte * 3),
        ("src1_gb_alpha",        ctypes.c_uint),
        ("src2_gb_alpha_en",     ctypes.c_ubyte),
        ("_pad2",                ctypes.c_ubyte * 3),
        ("src2_gb_alpha",        ctypes.c_uint),
        ("op_mode",              ctypes.c_uint),
        ("bitmask_en",           ctypes.c_ubyte),
        ("bytemask_only",        ctypes.c_ubyte),
        ("_pad3",                ctypes.c_ubyte * 2),
        ("bitmask",              ctypes.c_uint),
        ("dst_xy_swap",          ctypes.c_ubyte),
        ("_pad4",                ctypes.c_ubyte * 3),
        # scaler
        ("hf_init_phase",        ctypes.c_uint),
        ("hf_rpt_num",           ctypes.c_int),
        ("hsc_start_phase_step", ctypes.c_uint),
        ("hsc_phase_slope",      ctypes.c_int),
        ("vf_init_phase",        ctypes.c_uint),
        ("vf_rpt_num",           ctypes.c_int),
        ("vsc_start_phase_step", ctypes.c_uint),
        ("vsc_phase_slope",      ctypes.c_int),
        ("src1_vsc_phase0_always_en", ctypes.c_ubyte),
        ("src1_hsc_phase0_always_en", ctypes.c_ubyte),
        ("src1_hsc_rpt_ctrl",    ctypes.c_ubyte),
        ("src1_vsc_rpt_ctrl",    ctypes.c_ubyte),
        # offset 216 here — already 8-byte aligned, no padding needed
        ("src_planes",           _PlaneIon * 4),
        ("src2_planes",          _PlaneIon * 4),
        ("dst_planes",           _PlaneIon * 4),
    ]

# GE2D_CONFIG_EX_ION — original ION path (needs ION allocator, NOT for our DMA buffers)
GE2D_CONFIG_EX_ION = _IOW(_G, 0x03, ctypes.sizeof(_ConfigExIon))

# ---------------------------------------------------------------------------
# _ConfigMemType — extended config for GE2D_CONFIG_EX_MEM (DMA-BUF path)
# Use this for buffers allocated via GE2D_REQUEST_BUFF on G12A (S905D2)
# ---------------------------------------------------------------------------

# mem_alloc_type values (enum from ge2d.h)
AML_GE2D_MEM_ION    = 0
AML_GE2D_MEM_DMABUF = 1   # our GE2D-allocated DMA buffers
AML_GE2D_MEM_INVALID = 2

class _ConfigMemType(ctypes.Structure):
    """config_para_ex_memtype_s:
       ge2d_magic (4) + pad (4) + _ge2d_config_ex (504) + 3×mem_alloc_type (12) = 524 → pad to 528
    """
    _fields_ = [
        ("ge2d_magic",           ctypes.c_int),       # must = sizeof(this struct) = 528
        ("_pad_align",           ctypes.c_uint),      # aligns _ge2d_config_ex to offset 8
        ("_ge2d_config_ex",      _ConfigExIon),       # 504 bytes at offset 8
        ("src1_mem_alloc_type",  ctypes.c_uint),      # offset 512
        ("src2_mem_alloc_type",  ctypes.c_uint),      # offset 516
        ("dst_mem_alloc_type",   ctypes.c_uint),      # offset 520
        # ctypes adds 4 bytes trailing pad → sizeof = 528
    ]

# GE2D_CONFIG_EX_MEM = _IOW('G', 0x07, sizeof(config_ge2d_para_ex_s))
# config_ge2d_para_ex_s is union(config_para_ex_ion_s=504, config_para_ex_memtype_s=528) → 528
GE2D_CONFIG_EX_MEM = _IOW(_G, 0x07, ctypes.sizeof(_ConfigMemType))

class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("w", ctypes.c_int), ("h", ctypes.c_int)]

class _OpPara(ctypes.Structure):
    """ge2d_para_s — operation parameter for BLIT/FILLRECT/etc."""
    _fields_ = [
        ("color",     ctypes.c_uint),
        ("src1_rect", _Rect),
        ("src2_rect", _Rect),
        ("dst_rect",  _Rect),
        ("op",        ctypes.c_int),
    ]

class _DmaBufReq(ctypes.Structure):
    _fields_ = [("index", ctypes.c_int), ("len", ctypes.c_uint), ("dma_dir", ctypes.c_uint)]

class _DmaBufExp(ctypes.Structure):
    _fields_ = [("index", ctypes.c_int), ("flags", ctypes.c_uint), ("fd", ctypes.c_int)]

GE2D_REQUEST_BUFF  = _IOW(_G, 0x04, ctypes.sizeof(_DmaBufReq))
GE2D_EXP_BUFF      = _IOW(_G, 0x05, ctypes.sizeof(_DmaBufExp))
GE2D_FREE_BUFF     = _IOW(_G, 0x06, 4)
# cache sync (flush CPU→device before op; invalidate device→CPU after op)
GE2D_SYNC_DEVICE   = _IOW(_G, 0x08, 4)
GE2D_SYNC_CPU      = _IOW(_G, 0x09, 4)

def _sync_device(fd: int, idx: int):
    """Flush CPU cache so GE2D can read src buffer (call before blit)."""
    v = ctypes.c_int(idx)
    _libc.ioctl(fd, GE2D_SYNC_DEVICE, ctypes.byref(v))  # ignore if kernel lacks it

def _sync_cpu(fd: int, idx: int):
    """Invalidate CPU cache so CPU reads GE2D output (call after any op)."""
    v = ctypes.c_int(idx)
    _libc.ioctl(fd, GE2D_SYNC_CPU, ctypes.byref(v))  # ignore if kernel lacks it

# ---------------------------------------------------------------------------
# GE2D format constants
# ---------------------------------------------------------------------------

GE2D_FMT_RGBA    = 1   # PIXEL_FORMAT_RGBA_8888
GE2D_FMT_RGBX    = 2   # PIXEL_FORMAT_RGBX_8888
GE2D_FMT_RGB     = 3   # PIXEL_FORMAT_RGB_888
GE2D_FMT_RGB565  = 4   # PIXEL_FORMAT_RGB_565
GE2D_FMT_BGRA    = 5   # PIXEL_FORMAT_BGRA_8888

CANVAS_TYPE_INVALID = 3
CANVAS_ALLOC        = 2

# ge2d internal format codes (from ge2d.h)
# GE2D_FMT_S32_RGBA = GE2D_LITTLE_ENDIAN | 0x300  (32bpp = 0x300, NOT 0x100 which is 16bpp)
# GE2D_COLOR_MAP_*8888: RGBA=0, ARGB=1<<20, ABGR=2<<20, BGRA=3<<20
_GE2D_LITTLE_ENDIAN = 1 << 24
_FMT_BASE_32 = _GE2D_LITTLE_ENDIAN | 0x300   # 32bpp base
_FMT_BASE_24 = _GE2D_LITTLE_ENDIAN | 0x200   # 24bpp base
_FMT_BASE_16 = _GE2D_LITTLE_ENDIAN | 0x100   # 16bpp base

# libge2d mapping: PIXEL_FORMAT_RGBA_8888 → GE2D_FORMAT_S32_ARGB (color_map=1)
# This matches PIL 'RGBA' byte order [R,G,B,A] → GE2D ARGB value 0xAARRGGBB
_FMT_S32_ARGB  = _FMT_BASE_32 | (1 << 20)  # GE2D_FORMAT_S32_ARGB  — for PIL RGBA
_FMT_S32_RGBA  = _FMT_BASE_32 | (0 << 20)  # GE2D_FORMAT_S32_RGBA
_FMT_S32_ABGR  = _FMT_BASE_32 | (2 << 20)  # GE2D_FORMAT_S32_ABGR
_FMT_S32_BGRA  = _FMT_BASE_32 | (3 << 20)  # GE2D_FORMAT_S32_BGRA  — for PIL BGRA

_FMT_S24_RGB   = _FMT_BASE_24 | (0 << 20)  # GE2D_FORMAT_S24_RGB
_FMT_S16_RGB565 = _FMT_BASE_16 | (5 << 20) # GE2D_FORMAT_S16_RGB565

_BPP = {
    GE2D_FMT_RGBA:   (32, _FMT_S32_ARGB),  # PIL 'RGBA' → GE2D ARGB
    GE2D_FMT_RGBX:   (32, _FMT_S32_ARGB),
    GE2D_FMT_RGB:    (24, _FMT_S24_RGB),
    GE2D_FMT_RGB565: (16, _FMT_S16_RGB565),
    GE2D_FMT_BGRA:   (32, _FMT_S32_BGRA),  # PIL 'BGRA' → GE2D BGRA
}

def _canvas_aligned(x):
    return (x + 31) & ~31

def _canvas_w(width, bpp):
    return _canvas_aligned(width * bpp // 8)


# ---------------------------------------------------------------------------
# GE2DBuffer — DMA buffer allocated from GE2D driver
# ---------------------------------------------------------------------------

class GE2DBuffer:
    """DMA buffer allocated via GE2D_REQUEST_BUFF / GE2D_EXP_BUFF.

    Attributes:
        pixels   — mmap.mmap for CPU read/write
        width, height, fmt, stride  — geometry
        dma_fd   — exported DMA-BUF fd (can be shared with DRM via drmPrimeHandleToFD)
    """

    def __init__(self, ge2d_fd, width, height, fmt=GE2D_FMT_RGBA):
        self._ge2d_fd  = ge2d_fd
        self.width  = width
        self.height = height
        self.fmt    = fmt
        bpp, ge2d_fmt = _BPP[fmt]
        self._ge2d_fmt = ge2d_fmt
        self._bpp      = bpp
        self.stride = _canvas_w(width, bpp)
        self.size   = self.stride * height

        # allocate
        req = _DmaBufReq(0, self.size, 0)
        _ioctl(ge2d_fd, GE2D_REQUEST_BUFF, req)
        self._index = req.index

        # export as DMA-BUF fd
        exp = _DmaBufExp(self._index, os.O_RDWR, -1)
        _ioctl(ge2d_fd, GE2D_EXP_BUFF, exp)
        self.dma_fd = exp.fd

        # mmap for CPU access
        self.pixels = mmap.mmap(self.dma_fd, self.size)

    def write_bytes(self, data: bytes, offset: int = 0):
        self.pixels.seek(offset)
        self.pixels.write(data)

    def read_bytes(self, length: int, offset: int = 0) -> bytes:
        self.pixels.seek(offset)
        return self.pixels.read(length)

    def close(self):
        if self.pixels and not self.pixels.closed:
            self.pixels.close()
        if self.dma_fd >= 0:
            os.close(self.dma_fd)
            self.dma_fd = -1
        if self._index >= 0:
            free_v = ctypes.c_int(self._index)
            _libc.ioctl(self._ge2d_fd, GE2D_FREE_BUFF, ctypes.byref(free_v))
            self._index = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# GE2DDevice — main device handle
# ---------------------------------------------------------------------------

class GE2DDevice:
    """Amlogic GE2D 2D accelerator device handle."""

    def __init__(self, path="/dev/ge2d"):
        self._fd = os.open(path, os.O_RDWR)
        cap = ctypes.c_int(0)
        _libc.ioctl(self._fd, GE2D_GET_CAP, ctypes.byref(cap))
        self.cap_attr = cap.value

    def alloc(self, width: int, height: int, fmt: int = GE2D_FMT_RGBA) -> GE2DBuffer:
        return GE2DBuffer(self._fd, width, height, fmt)

    # -----------------------------------------------------------------------
    # _configure — set up src/dst buffers for the next operation
    # -----------------------------------------------------------------------

    def _configure(self, dst: GE2DBuffer,
                   src: GE2DBuffer | None = None,
                   src2: GE2DBuffer | None = None):
        wrap = _ConfigMemType()
        ctypes.memset(ctypes.byref(wrap), 0, ctypes.sizeof(wrap))
        wrap.ge2d_magic = ctypes.sizeof(_ConfigMemType)  # driver checks this == 528
        ex = wrap._ge2d_config_ex

        # dst
        d_bpp, d_fmt = _BPP[dst.fmt]
        d_cw = _canvas_w(dst.width, d_bpp)
        ex.dst_para.mem_type = CANVAS_ALLOC
        ex.dst_para.format   = d_fmt
        ex.dst_para.left     = 0
        ex.dst_para.top      = 0
        ex.dst_para.width    = d_cw
        ex.dst_para.height   = dst.height
        ex.dst_planes[0].shared_fd = dst.dma_fd
        ex.dst_planes[0].w = d_cw
        ex.dst_planes[0].h = dst.height
        wrap.dst_mem_alloc_type = AML_GE2D_MEM_DMABUF

        # src
        if src is not None:
            s_bpp, s_fmt = _BPP[src.fmt]
            s_cw = _canvas_w(src.width, s_bpp)
            ex.src_para.mem_type = CANVAS_ALLOC
            ex.src_para.format   = s_fmt
            ex.src_para.left     = 0
            ex.src_para.top      = 0
            ex.src_para.width    = s_cw
            ex.src_para.height   = src.height
            ex.src_planes[0].shared_fd = src.dma_fd
            ex.src_planes[0].w = s_cw
            ex.src_planes[0].h = src.height
            wrap.src1_mem_alloc_type = AML_GE2D_MEM_DMABUF
        else:
            ex.src_para.mem_type = CANVAS_TYPE_INVALID
            wrap.src1_mem_alloc_type = AML_GE2D_MEM_INVALID

        # src2
        if src2 is not None:
            s2_bpp, s2_fmt = _BPP[src2.fmt]
            s2_cw = _canvas_w(src2.width, s2_bpp)
            ex.src2_para.mem_type = CANVAS_ALLOC
            ex.src2_para.format   = s2_fmt
            ex.src2_para.width    = s2_cw
            ex.src2_para.height   = src2.height
            ex.src2_planes[0].shared_fd = src2.dma_fd
            ex.src2_planes[0].w = s2_cw
            ex.src2_planes[0].h = src2.height
            wrap.src2_mem_alloc_type = AML_GE2D_MEM_DMABUF
        else:
            ex.src2_para.mem_type = CANVAS_TYPE_INVALID
            wrap.src2_mem_alloc_type = AML_GE2D_MEM_INVALID

        _ioctl(self._fd, GE2D_CONFIG_EX_MEM, wrap)

    # -----------------------------------------------------------------------
    # fillrect — hardware fill rectangle with solid color
    # -----------------------------------------------------------------------

    def fillrect(self, dst: GE2DBuffer, color: int,
                 x: int = 0, y: int = 0,
                 w: int = -1, h: int = -1):
        """Fill rectangle on dst with color in RGBA format (0xRRGGBBAA).

        Examples: red=0xFF0000FF, green=0x00FF00FF, blue=0x0000FFFF, white=0xFFFFFFFF.
        The GE2D hardware rotates bytes: buffer bytes = [B, G, R, A] = DRM XRGB8888-compatible.
        """
        if w < 0: w = dst.width
        if h < 0: h = dst.height
        self._configure(dst)
        op = _OpPara()
        ctypes.memset(ctypes.byref(op), 0, ctypes.sizeof(op))
        op.color = color
        op.src1_rect.x = x; op.src1_rect.y = y
        op.src1_rect.w = w; op.src1_rect.h = h
        op.dst_rect.x = x; op.dst_rect.y = y
        op.dst_rect.w = w; op.dst_rect.h = h
        _ioctl(self._fd, GE2D_FILLRECTANGLE, op)
        _sync_cpu(self._fd, dst._index)

    # -----------------------------------------------------------------------
    # blit — hardware pixel copy (src region → dst region, same size)
    # -----------------------------------------------------------------------

    def blit(self, src: GE2DBuffer, dst: GE2DBuffer,
             sx: int = 0, sy: int = 0,
             w: int  = -1, h: int = -1,
             dx: int = 0, dy: int = 0):
        """Copy rectangle from src to dst (no scaling)."""
        if w < 0: w = src.width
        if h < 0: h = src.height
        self._configure(dst, src=src)
        _sync_device(self._fd, src._index)
        op = _OpPara()
        ctypes.memset(ctypes.byref(op), 0, ctypes.sizeof(op))
        op.src1_rect.x = sx; op.src1_rect.y = sy
        op.src1_rect.w = w;  op.src1_rect.h = h
        op.dst_rect.x  = dx; op.dst_rect.y  = dy
        op.dst_rect.w  = w;  op.dst_rect.h  = h
        _ioctl(self._fd, GE2D_BLIT, op)
        _sync_cpu(self._fd, dst._index)

    # -----------------------------------------------------------------------
    # stretchblit — hardware scaled blit (arbitrary src→dst rect)
    # -----------------------------------------------------------------------

    def stretchblit(self, src: GE2DBuffer, dst: GE2DBuffer,
                    sx: int, sy: int, sw: int, sh: int,
                    dx: int, dy: int, dw: int, dh: int):
        """Scale src_rect → dst_rect using hardware bilinear scaler."""
        self._configure(dst, src=src)
        _sync_device(self._fd, src._index)
        op = _OpPara()
        ctypes.memset(ctypes.byref(op), 0, ctypes.sizeof(op))
        op.src1_rect.x = sx; op.src1_rect.y = sy
        op.src1_rect.w = sw; op.src1_rect.h = sh
        op.dst_rect.x  = dx; op.dst_rect.y  = dy
        op.dst_rect.w  = dw; op.dst_rect.h  = dh
        _ioctl(self._fd, GE2D_STRETCHBLIT, op)
        _sync_cpu(self._fd, dst._index)

    # -----------------------------------------------------------------------
    # blend — hardware alpha compositing: src1 over src2 → dst
    # -----------------------------------------------------------------------

    def blend(self, src1: GE2DBuffer, src2: GE2DBuffer, dst: GE2DBuffer,
              sx: int = 0, sy: int = 0,
              w:  int = -1, h: int = -1,
              dx: int = 0, dy: int = 0,
              global_alpha: int = 255):
        """Hardware alpha blend: out = src1 * src1.alpha + src2 * (1 - src1.alpha)."""
        if w < 0: w = dst.width
        if h < 0: h = dst.height
        self._configure(dst, src=src1, src2=src2)
        _sync_device(self._fd, src1._index)
        _sync_device(self._fd, src2._index)
        op = _OpPara()
        ctypes.memset(ctypes.byref(op), 0, ctypes.sizeof(op))
        op.src1_rect.x = sx; op.src1_rect.y = sy
        op.src1_rect.w = w;  op.src1_rect.h = h
        op.src2_rect.x = dx; op.src2_rect.y = dy
        op.src2_rect.w = w;  op.src2_rect.h = h
        op.dst_rect.x  = dx; op.dst_rect.y  = dy
        op.dst_rect.w  = w;  op.dst_rect.h  = h
        _ioctl(self._fd, GE2D_BLEND, op)
        _sync_cpu(self._fd, dst._index)

    def close(self):
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
