/* Мини-libc для freestanding libsbc: memcpy/memset + bump-malloc.
 * malloc зовётся ТОЛЬКО из sbc_init (один priv ~600Б на кодек) — пула хватит
 * на десятки экземпляров; free — no-op (кодеки живут вечно в процессе). */
typedef __SIZE_TYPE__ size_t;

void *memcpy(void *dst, const void *src, size_t n)
{
    char *d = dst; const char *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *memset(void *s, int c, size_t n)
{
    char *p = s;
    while (n--) *p++ = (char)c;
    return s;
}

static char _pool[64 * 1024];
static size_t _pool_off;

void *malloc(size_t n)
{
    n = (n + 15) & ~(size_t)15;
    if (_pool_off + n > sizeof(_pool)) return 0;
    void *p = _pool + _pool_off;
    _pool_off += n;
    return p;
}

void free(void *p) { (void)p; }
