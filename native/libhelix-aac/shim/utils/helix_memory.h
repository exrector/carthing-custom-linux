#pragma once

/* The C decoder core calls helix_malloc/helix_free directly from buffers.c.
 * The Arduino wrapper normally provides this header; the freestanding build
 * only needs the declarations.
 */

void *helix_malloc(int n);
void helix_free(void *p);
