#include <stdint.h>

int carthing_rotate_rgb_to_bgrx_cw(const uint8_t *src,
                                   int src_w,
                                   int src_h,
                                   uint8_t *dst,
                                   int dst_w,
                                   int dst_h,
                                   int dst_stride)
{
    if (!src || !dst || src_w <= 0 || src_h <= 0 ||
        dst_w != src_h || dst_h != src_w || dst_stride < dst_w * 4) {
        return -1;
    }

    for (int dy = 0; dy < dst_h; dy++) {
        uint8_t *out = dst + (uint64_t)dy * (uint64_t)dst_stride;
        const int sx = dy;

        for (int dx = 0; dx < dst_w; dx++) {
            const int sy = src_h - 1 - dx;
            const uint8_t *p = src + ((uint64_t)sy * (uint64_t)src_w + (uint64_t)sx) * 3u;

            out[0] = p[2];
            out[1] = p[1];
            out[2] = p[0];
            out[3] = 0;
            out += 4;
        }
    }

    return 0;
}
