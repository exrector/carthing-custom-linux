/* Мини-libc для freestanding helix-aac (тот же подход, что native/libsbc):
 * helix_malloc зовётся при создании декодера (AACDecInfo+PSInfoBase, ~50КБ
 * суммарно) — bump-пул 256К хватит на несколько экземпляров; free — no-op. */
typedef __SIZE_TYPE__ size_t;

void *memcpy(void *dst, const void *src, size_t n)
{ char *d = dst; const char *s = src; while (n--) *d++ = *s++; return dst; }

void *memset(void *s, int c, size_t n)
{ char *p = s; while (n--) *p++ = (char)c; return s; }

void *memmove(void *dst, const void *src, size_t n)
{
    char *d = dst; const char *s = src;
    if (d < s) { while (n--) *d++ = *s++; }
    else { d += n; s += n; while (n--) *--d = *--s; }
    return dst;
}

static char _pool[256 * 1024];
static size_t _off;
void *malloc(size_t n)
{ n = (n + 15) & ~(size_t)15; if (_off + n > sizeof(_pool)) return 0;
  void *p = _pool + _off; _off += n; return p; }
void free(void *p) { (void)p; }
void *helix_malloc(int n) { return malloc((size_t)n); }
void helix_free(void *p) { free(p); }
