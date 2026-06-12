#ifndef _SHIM_STRING_H
#define _SHIM_STRING_H
typedef __SIZE_TYPE__ size_t;
void *memcpy(void *dst, const void *src, size_t n);
void *memset(void *s, int c, size_t n);
#endif
