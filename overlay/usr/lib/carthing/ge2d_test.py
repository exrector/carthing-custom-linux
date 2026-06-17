#!/usr/bin/env python3
"""GE2D diagnostic test — struct sizes, ioctl codes, operations."""
import ctypes
import sys
import os
sys.path.insert(0, '/usr/lib/carthing')
import ge2d

print("=== struct sizes ===")
print(f"_SrcDstPara       = {ctypes.sizeof(ge2d._SrcDstPara)} bytes  (expect 36)")
print(f"_SrcKeyCtrl       = {ctypes.sizeof(ge2d._SrcKeyCtrl)} bytes  (expect 16)")
print(f"_PlaneIon         = {ctypes.sizeof(ge2d._PlaneIon)} bytes  (expect 24)")
print(f"_ConfigExIon      = {ctypes.sizeof(ge2d._ConfigExIon)} bytes (expect 504)")
print(f"_OpPara           = {ctypes.sizeof(ge2d._OpPara)} bytes  (expect 52)")
print(f"_DmaBufReq        = {ctypes.sizeof(ge2d._DmaBufReq)} bytes  (expect 12)")
print(f"_DmaBufExp        = {ctypes.sizeof(ge2d._DmaBufExp)} bytes  (expect 12)")

print("\n=== ioctl codes ===")
print(f"GE2D_CONFIG_EX_ION = 0x{ge2d.GE2D_CONFIG_EX_ION:08x}  (expect 0x41f84703)")
print(f"GE2D_REQUEST_BUFF  = 0x{ge2d.GE2D_REQUEST_BUFF:08x}  (expect 0x400c4704)")
print(f"GE2D_EXP_BUFF      = 0x{ge2d.GE2D_EXP_BUFF:08x}  (expect 0x400c4705)")
print(f"GE2D_SYNC_DEVICE   = 0x{ge2d.GE2D_SYNC_DEVICE:08x}  (expect 0x40044708)")
print(f"GE2D_SYNC_CPU      = 0x{ge2d.GE2D_SYNC_CPU:08x}  (expect 0x40044709)")
print(f"GE2D_FILLRECTANGLE = 0x{ge2d.GE2D_FILLRECTANGLE:08x}")
print(f"GE2D_BLIT          = 0x{ge2d.GE2D_BLIT:08x}")

print("\n=== _ConfigExIon field offsets ===")
cfg = ge2d._ConfigExIon
for name, _ in cfg._fields_:
    off = getattr(cfg, name).offset
    print(f"  {name:<30} offset={off}")

if not os.path.exists('/dev/ge2d'):
    print("\n/dev/ge2d not found — run on device")
    sys.exit(0)

print("\n=== device open ===")
dev = ge2d.GE2DDevice()
print(f"cap_attr = {dev.cap_attr}")

print("\n=== alloc 200x200 RGBA ===")
buf_a = dev.alloc(200, 200, ge2d.GE2D_FMT_RGBA)
buf_b = dev.alloc(200, 200, ge2d.GE2D_FMT_RGBA)
print(f"buf_a: stride={buf_a.stride} size={buf_a.size} dma_fd={buf_a.dma_fd} idx={buf_a._index}")
print(f"buf_b: stride={buf_b.stride} size={buf_b.size} dma_fd={buf_b.dma_fd} idx={buf_b._index}")

# --- fillrect test ---
print("\n=== fillrect: красный 200x200 в buf_a ===")
# pre-zero buf_a so we know initial state
buf_a.pixels.seek(0)
buf_a.pixels.write(b'\x00' * buf_a.size)
dev.fillrect(buf_a, color=0xFF0000FF, x=0, y=0, w=200, h=200)
buf_a.pixels.seek(0)
px = buf_a.pixels.read(4)
print(f"pixel[0,0] = {tuple(px)}  (expect 255,0,0,255 for red RGBA or 0,0,255,255 for GE2D ABGR)")

# --- fill green in buf_b, then blit to buf_a ---
print("\n=== fill buf_b зелёным, затем blit buf_b -> buf_a ===")
dev.fillrect(buf_b, color=0x00FF00FF, x=0, y=0, w=200, h=200)
buf_b.pixels.seek(0)
px_b = buf_b.pixels.read(4)
print(f"buf_b pixel[0,0] after fillrect = {tuple(px_b)}")

# clear buf_a
buf_a.pixels.seek(0)
buf_a.pixels.write(b'\x00' * buf_a.size)
dev.blit(buf_b, buf_a, sx=0, sy=0, w=50, h=50, dx=0, dy=0)
buf_a.pixels.seek(0)
px_blit = buf_a.pixels.read(4)
print(f"buf_a pixel[0,0] after blit    = {tuple(px_blit)}  (expect same as buf_b's green)")

# cleanup
buf_a.close()
buf_b.close()
dev.close()
print("\nDONE")
