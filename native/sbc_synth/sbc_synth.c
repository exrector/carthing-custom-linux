/* Горячий синтез SBC (8/4 поддиапазонов) — вынос из sbc_decoder.py.
 * Python даёт 0.5x realtime на A53; этот файл — запас в десятки раз.
 * Алгоритм идентичен bluez sbc_synthesize_eight/four (fixed-point, >>15);
 * таблицы передаёт Python при инициализации (ctypes).
 *
 * Сборка НА MAC (freestanding, ни одного вызова libc — sysroot не нужен):
 *   clang -target aarch64-unknown-linux-gnu -O2 -fPIC -shared -nostdlib \
 *         -o sbc_synth.so sbc_synth.c
 * [CLAUDE 2026-06-12] ABI менять синхронно с sbc_decoder.py. */
typedef int int32_t;
typedef short int16_t;

static inline int16_t clip16(int32_t s)
{
    if (s > 0x7FFF) return 0x7FFF;
    if (s < -0x8000) return -0x8000;
    return (int16_t)s;
}

void sbc_synth8(int32_t *v, int32_t *offset,
                const int32_t *sb_sample, int32_t blocks,
                const int32_t *synmatrix, const int32_t *m0, const int32_t *m1,
                int16_t *out)
{
    for (int32_t blk = 0; blk < blocks; blk++) {
        const int32_t *s = sb_sample + blk * 8;
        for (int32_t i = 0; i < 16; i++) {
            int32_t off = offset[i] - 1;
            if (off < 0) {
                off = 159;
                for (int32_t j = 0; j < 9; j++)
                    v[160 + j] = v[j];
            }
            offset[i] = off;
            const int32_t *row = synmatrix + i * 8;
            v[off] = (row[0]*s[0] + row[1]*s[1] + row[2]*s[2] + row[3]*s[3] +
                      row[4]*s[4] + row[5]*s[5] + row[6]*s[6] + row[7]*s[7]) >> 15;
        }
        for (int32_t i = 0; i < 8; i++) {
            int32_t oi = offset[i];
            int32_t ok = offset[(i + 8) & 0xF];
            const int32_t *a = m0 + i * 5;
            const int32_t *b = m1 + i * 5;
            out[blk * 8 + i] = clip16((v[oi]     * a[0] + v[ok + 1] * b[0] +
                                       v[oi + 2] * a[1] + v[ok + 3] * b[1] +
                                       v[oi + 4] * a[2] + v[ok + 5] * b[2] +
                                       v[oi + 6] * a[3] + v[ok + 7] * b[3] +
                                       v[oi + 8] * a[4] + v[ok + 9] * b[4]) >> 15);
        }
    }
}

void sbc_synth4(int32_t *v, int32_t *offset,
                const int32_t *sb_sample, int32_t blocks,
                const int32_t *synmatrix, const int32_t *m0, const int32_t *m1,
                int16_t *out)
{
    for (int32_t blk = 0; blk < blocks; blk++) {
        const int32_t *s = sb_sample + blk * 4;
        for (int32_t i = 0; i < 8; i++) {
            int32_t off = offset[i] - 1;
            if (off < 0) {
                off = 79;
                for (int32_t j = 0; j < 9; j++)
                    v[80 + j] = v[j];
            }
            offset[i] = off;
            const int32_t *row = synmatrix + i * 4;
            v[off] = (row[0]*s[0] + row[1]*s[1] + row[2]*s[2] + row[3]*s[3]) >> 15;
        }
        for (int32_t i = 0; i < 4; i++) {
            int32_t oi = offset[i];
            int32_t ok = offset[(i + 4) & 0x7];
            const int32_t *a = m0 + i * 5;
            const int32_t *b = m1 + i * 5;
            out[blk * 4 + i] = clip16((v[oi]     * a[0] + v[ok + 1] * b[0] +
                                       v[oi + 2] * a[1] + v[ok + 3] * b[1] +
                                       v[oi + 4] * a[2] + v[ok + 5] * b[2] +
                                       v[oi + 6] * a[3] + v[ok + 7] * b[3] +
                                       v[oi + 8] * a[4] + v[ok + 9] * b[4]) >> 15);
        }
    }
}
