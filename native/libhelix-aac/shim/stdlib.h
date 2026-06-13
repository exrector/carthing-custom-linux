#ifndef _SHIM_STDLIB_H
#define _SHIM_STDLIB_H
typedef __SIZE_TYPE__ size_t;
void *malloc(size_t n);
void free(void *p);
#endif
