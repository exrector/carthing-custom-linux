#!/usr/bin/env python3
"""GE2D diagnostic test — struct sizes, ioctl codes, operations, color mapping."""
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
print(f"_ConfigMemType    = {ctypes.sizeof(ge2d._ConfigMemType)} bytes (expect 528)")
print(f"_OpPara           = {ctypes.sizeof(ge2d._OpPara)} bytes  (expect 56)")
print(f"_DmaBufReq        = {ctypes.sizeof(ge2d._DmaBufReq)} bytes  (expect 12)")
print(f"_DmaBufExp        = {ctypes.sizeof(ge2d._DmaBufExp)} bytes  (expect 12)")

print("\n=== ioctl codes ===")
print(f"GE2D_CONFIG_EX_ION = 0x{ge2d.GE2D_CONFIG_EX_ION:08x}  (expect 0x41f84703)")
print(f"GE2D_CONFIG_EX_MEM = 0x{ge2d.GE2D_CONFIG_EX_MEM:08x}  (expect 0x42104707)")
print(f"GE2D_REQUEST_BUFF  = 0x{ge2d.GE2D_REQUEST_BUFF:08x}  (expect 0x400c4704)")
print(f"GE2D_EXP_BUFF      = 0x{ge2d.GE2D_EXP_BUFF:08x}  (expect 0x400c4705)")
print(f"GE2D_SYNC_DEVICE   = 0x{ge2d.GE2D_SYNC_DEVICE:08x}  (expect 0x40044708)")
print(f"GE2D_SYNC_CPU      = 0x{ge2d.GE2D_SYNC_CPU:08x}  (expect 0x40044709)")
print(f"GE2D_FILLRECTANGLE = 0x{ge2d.GE2D_FILLRECTANGLE:08x}")
print(f"GE2D_BLIT          = 0x{ge2d.GE2D_BLIT:08x}")

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

def check_fill(dev, buf, color, expect_bytes, label):
    """Fill buf with color, read first pixel, compare."""
    buf.pixels.seek(0)
    buf.pixels.write(b'\x00' * buf.size)
    dev.fillrect(buf, color=color, x=0, y=0, w=200, h=200)
    buf.pixels.seek(0)
    px = buf.pixels.read(4)
    ok = bytes(px) == bytes(expect_bytes)
    status = "OK" if ok else f"FAIL got {tuple(px)}"
    print(f"  fillrect({label}=0x{color:08x}) → {tuple(px)}  expect={tuple(expect_bytes)}  {status}")
    return ok

# Color format: 0xRRGGBBAA
# Buffer layout: [B, G, R, A] = DRM XRGB8888-compatible
# expect_bytes = (B, G, R, A) in DRM order
print("\n=== fillrect color mapping (color=0xRRGGBBAA) ===")
all_ok = True
all_ok &= check_fill(dev, buf_a, 0xFF0000FF, (0x00, 0x00, 0xFF, 0xFF), "red   ")
all_ok &= check_fill(dev, buf_a, 0x00FF00FF, (0x00, 0xFF, 0x00, 0xFF), "green ")
all_ok &= check_fill(dev, buf_a, 0x0000FFFF, (0xFF, 0x00, 0x00, 0xFF), "blue  ")
all_ok &= check_fill(dev, buf_a, 0xFFFFFFFF, (0xFF, 0xFF, 0xFF, 0xFF), "white ")
all_ok &= check_fill(dev, buf_a, 0x000000FF, (0x00, 0x00, 0x00, 0xFF), "black ")
all_ok &= check_fill(dev, buf_a, 0x00000000, (0x00, 0x00, 0x00, 0x00), "transp")
print(f"  OVERALL: {'✓ ALL PASS' if all_ok else '✗ SOME FAILED'}")

# blit test
print("\n=== blit buf_a → buf_b ===")
dev.fillrect(buf_a, color=0xFF0000FF, x=0, y=0, w=200, h=200)  # red
buf_b.pixels.seek(0)
buf_b.pixels.write(b'\x00' * buf_b.size)
dev.blit(buf_a, buf_b, sx=0, sy=0, w=200, h=200, dx=0, dy=0)
buf_b.pixels.seek(0)
px_dst = buf_b.pixels.read(4)
buf_a.pixels.seek(0)
px_src = buf_a.pixels.read(4)
match = bytes(px_dst) == bytes(px_src)
print(f"  blit result={tuple(px_dst)}  src={tuple(px_src)}  {'✓ OK' if match else '✗ FAIL'}")

buf_a.close()
buf_b.close()
dev.close()
print("\nDONE")
