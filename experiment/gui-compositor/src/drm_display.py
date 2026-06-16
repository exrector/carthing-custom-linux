"""
Minimal DRM/KMS framebuffer for Amlogic meson-drm (Car Thing 480×800).
Creates a dumb buffer, maps it, sets CRTC — exposes a writable mmap.
"""
import ctypes, ctypes.util, mmap, os, logging

_libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
_libc.ioctl.restype = ctypes.c_int
_libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]

log = logging.getLogger(__name__)

# ─── ioctl numbers (aarch64, 64-bit kernel) ───────────────────────────────────
def _IOC(d, t, n, s): return (d<<30)|(s<<16)|(t<<8)|n
DRM_IOWR = lambda n, s: _IOC(3, 0x64, n, s)
DRM_IOW  = lambda n, s: _IOC(1, 0x64, n, s)
DRM_IOR  = lambda n, s: _IOC(2, 0x64, n, s)

GETRES     = DRM_IOWR(0xA0, 64)   # drm_mode_card_res      64B
GETCONN    = DRM_IOWR(0xA7, 80)   # drm_mode_get_connector 80B
GETENC     = DRM_IOWR(0xA6, 20)   # drm_mode_get_encoder   20B
GETCRTC    = DRM_IOWR(0xA1, 104)  # drm_mode_crtc         104B
SETCRTC    = DRM_IOWR(0xA2, 104)
ADDFB      = DRM_IOWR(0xAE, 28)   # drm_mode_fb_cmd        28B
CREATEDUMB = DRM_IOWR(0xB2, 32)   # drm_mode_create_dumb   32B
MAPDUMB    = DRM_IOWR(0xB3, 16)   # drm_mode_map_dumb      16B

# ─── ctypes structs ──────────────────────────────────────────────────────────
class Res(ctypes.Structure):
    _fields_ = [
        ('fb_id_ptr',        ctypes.c_uint64),
        ('crtc_id_ptr',      ctypes.c_uint64),
        ('connector_id_ptr', ctypes.c_uint64),
        ('encoder_id_ptr',   ctypes.c_uint64),
        ('count_fbs',        ctypes.c_uint32),
        ('count_crtcs',      ctypes.c_uint32),
        ('count_connectors', ctypes.c_uint32),
        ('count_encoders',   ctypes.c_uint32),
        ('min_width',        ctypes.c_uint32),
        ('max_width',        ctypes.c_uint32),
        ('min_height',       ctypes.c_uint32),
        ('max_height',       ctypes.c_uint32),
    ]

class Connector(ctypes.Structure):
    _fields_ = [
        ('encoders_ptr',       ctypes.c_uint64),
        ('modes_ptr',          ctypes.c_uint64),
        ('props_ptr',          ctypes.c_uint64),
        ('prop_values_ptr',    ctypes.c_uint64),
        ('count_modes',        ctypes.c_uint32),
        ('count_props',        ctypes.c_uint32),
        ('count_encoders',     ctypes.c_uint32),
        ('encoder_id',         ctypes.c_uint32),
        ('connector_id',       ctypes.c_uint32),
        ('connector_type',     ctypes.c_uint32),
        ('connector_type_id',  ctypes.c_uint32),
        ('connection',         ctypes.c_uint32),
        ('mm_width',           ctypes.c_uint32),
        ('mm_height',          ctypes.c_uint32),
        ('subpixel',           ctypes.c_uint32),
        ('pad',                ctypes.c_uint32),
    ]

class Encoder(ctypes.Structure):
    _fields_ = [
        ('encoder_id',    ctypes.c_uint32),
        ('encoder_type',  ctypes.c_uint32),
        ('crtc_id',       ctypes.c_uint32),
        ('possible_crtcs',ctypes.c_uint32),
        ('possible_clones',ctypes.c_uint32),
    ]

class ModeInfo(ctypes.Structure):
    _fields_ = [
        ('clock',        ctypes.c_uint32),
        ('hdisplay',     ctypes.c_uint16), ('hsync_start', ctypes.c_uint16),
        ('hsync_end',    ctypes.c_uint16), ('htotal',      ctypes.c_uint16),
        ('hskew',        ctypes.c_uint16),
        ('vdisplay',     ctypes.c_uint16), ('vsync_start', ctypes.c_uint16),
        ('vsync_end',    ctypes.c_uint16), ('vtotal',      ctypes.c_uint16),
        ('vscan',        ctypes.c_uint16),
        ('vrefresh',     ctypes.c_uint32),
        ('flags',        ctypes.c_uint32),
        ('type',         ctypes.c_uint32),
        ('name',         ctypes.c_char * 32),
    ]

class CrtcCmd(ctypes.Structure):
    _fields_ = [
        ('set_connectors_ptr', ctypes.c_uint64),
        ('count_connectors',   ctypes.c_uint32),
        ('crtc_id',            ctypes.c_uint32),
        ('fb_id',              ctypes.c_uint32),
        ('x',                  ctypes.c_uint32),
        ('y',                  ctypes.c_uint32),
        ('gamma_size',         ctypes.c_uint32),
        ('mode_valid',         ctypes.c_uint32),
        ('mode',               ModeInfo),
    ]

class CreateDumb(ctypes.Structure):
    _fields_ = [
        ('height', ctypes.c_uint32),
        ('width',  ctypes.c_uint32),
        ('bpp',    ctypes.c_uint32),
        ('flags',  ctypes.c_uint32),
        ('handle', ctypes.c_uint32),
        ('pitch',  ctypes.c_uint32),
        ('size',   ctypes.c_uint64),
    ]

class MapDumb(ctypes.Structure):
    _fields_ = [
        ('handle', ctypes.c_uint32),
        ('pad',    ctypes.c_uint32),
        ('offset', ctypes.c_uint64),
    ]

class AddFB(ctypes.Structure):
    _fields_ = [
        ('fb_id',  ctypes.c_uint32),
        ('width',  ctypes.c_uint32),
        ('height', ctypes.c_uint32),
        ('pitch',  ctypes.c_uint32),
        ('bpp',    ctypes.c_uint32),
        ('depth',  ctypes.c_uint32),
        ('handle', ctypes.c_uint32),
    ]


class DRMDisplay:
    def __init__(self, device='/dev/dri/card0'):
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        self._setup()

    def _ioctl(self, code, struct):
        ret = _libc.ioctl(self.fd, ctypes.c_ulong(code),
                          ctypes.c_void_p(ctypes.addressof(struct)))
        if ret != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))

    def _setup(self):
        # Get resources
        res = Res()
        self._ioctl(GETRES, res)
        log.info("DRM: %d connectors, %d CRTCs", res.count_connectors, res.count_crtcs)

        # Allocate all ID arrays (kernel writes to all non-null ptrs)
        conn_ids = (ctypes.c_uint32 * max(res.count_connectors, 1))()
        crtc_ids = (ctypes.c_uint32 * max(res.count_crtcs, 1))()
        enc_ids  = (ctypes.c_uint32 * max(res.count_encoders, 1))()
        fb_ids   = (ctypes.c_uint32 * max(res.count_fbs, 1))()
        res.connector_id_ptr = ctypes.addressof(conn_ids)
        res.crtc_id_ptr      = ctypes.addressof(crtc_ids)
        res.encoder_id_ptr   = ctypes.addressof(enc_ids)
        res.fb_id_ptr        = ctypes.addressof(fb_ids)
        self._ioctl(GETRES, res)

        # Find connected connector with modes
        conn = Connector()
        chosen_conn = None
        for i in range(res.count_connectors):
            conn.connector_id = conn_ids[i]
            conn.count_modes = 0
            self._ioctl(GETCONN, conn)
            if conn.count_modes > 0:
                chosen_conn = conn_ids[i]
                log.info("DRM: connector %d has %d modes", conn_ids[i], conn.count_modes)
                break

        if chosen_conn is None:
            # Use first connector anyway
            chosen_conn = conn_ids[0]
            conn.connector_id = chosen_conn
            conn.count_modes = 0
            self._ioctl(GETCONN, conn)

        # Get modes — allocate ALL pointer arrays (same two-pass pattern as GETRES)
        modes = (ModeInfo * max(conn.count_modes, 1))()
        conn.modes_ptr = ctypes.addressof(modes)
        enc_ids = (ctypes.c_uint32 * max(conn.count_encoders, 1))()
        conn.encoders_ptr = ctypes.addressof(enc_ids)
        props_arr = (ctypes.c_uint32 * max(conn.count_props, 1))()
        prop_vals_arr = (ctypes.c_uint64 * max(conn.count_props, 1))()
        conn.props_ptr = ctypes.addressof(props_arr)
        conn.prop_values_ptr = ctypes.addressof(prop_vals_arr)
        self._ioctl(GETCONN, conn)

        mode = modes[0]
        self.width  = mode.hdisplay
        self.height = mode.vdisplay
        log.info("DRM: mode %dx%d @%d", self.width, self.height, mode.vrefresh)

        # Get CRTC via encoder
        enc = Encoder()
        enc.encoder_id = conn.encoder_id if conn.encoder_id else enc_ids[0]
        self._ioctl(GETENC, enc)
        self.crtc_id = enc.crtc_id if enc.crtc_id else crtc_ids[0]

        # Create dumb buffer (XRGB8888 = 32bpp)
        dumb = CreateDumb()
        dumb.width  = self.width
        dumb.height = self.height
        dumb.bpp    = 32
        self._ioctl(CREATEDUMB, dumb)
        self.handle = dumb.handle
        self.pitch  = dumb.pitch
        self.size   = dumb.size
        log.info("DRM: dumb buffer %dx%d pitch=%d size=%d", self.width, self.height, self.pitch, self.size)

        # Add framebuffer
        fb = AddFB()
        fb.width  = self.width
        fb.height = self.height
        fb.pitch  = self.pitch
        fb.bpp    = 32
        fb.depth  = 24
        fb.handle = self.handle
        self._ioctl(ADDFB, fb)
        self.fb_id = fb.fb_id

        # Map dumb buffer
        dm = MapDumb()
        dm.handle = self.handle
        self._ioctl(MAPDUMB, dm)
        self.buf = mmap.mmap(self.fd, self.size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE,
                             offset=dm.offset)

        # Set CRTC
        conn_arr = (ctypes.c_uint32 * 1)(chosen_conn)
        crtc = CrtcCmd()
        crtc.set_connectors_ptr = ctypes.addressof(conn_arr)
        crtc.count_connectors   = 1
        crtc.crtc_id            = self.crtc_id
        crtc.fb_id              = self.fb_id
        crtc.x = crtc.y         = 0
        crtc.mode_valid         = 1
        crtc.mode               = mode
        self._ioctl(SETCRTC, crtc)
        log.info("DRM: CRTC set — display active")

    def blit(self, img_bytes: bytes):
        """Write XRGB8888 rows into the dumb buffer (respects DRM pitch/stride)."""
        row_bytes = self.width * 4
        if len(img_bytes) < row_bytes * self.height:
            log.warning("DRM blit: short frame %d < %d", len(img_bytes), row_bytes * self.height)
            return
        if self.pitch == row_bytes:
            self.buf.seek(0)
            self.buf.write(img_bytes[: row_bytes * self.height])
            return
        # Kernel may pad each scanline (pitch > width*4); compact RGBA/BGRX won't fit.
        mv = memoryview(self.buf)
        src = memoryview(img_bytes)
        for y in range(self.height):
            start = y * row_bytes
            mv[y * self.pitch : y * self.pitch + row_bytes] = src[start : start + row_bytes]

    def fill_test(self, rgb=(0, 200, 120)):
        """Solid colour frame — quick on-device sanity check for DRM output."""
        r, g, b = rgb
        row = bytes((b, g, r, 0)) * self.width
        if self.pitch == len(row):
            pattern = row * self.height
            self.buf.seek(0)
            self.buf.write(pattern)
            return
        mv = memoryview(self.buf)
        for y in range(self.height):
            mv[y * self.pitch : y * self.pitch + len(row)] = row

    def buffer_address(self) -> int:
        """Return the mmap base address for native render backends."""
        return ctypes.addressof(ctypes.c_char.from_buffer(memoryview(self.buf)))

    def close(self):
        self.buf.close()
        os.close(self.fd)
