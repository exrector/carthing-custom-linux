/* freestanding-сборка bluez libsbc: config.h включается первым —
 * протаскиваем компиляторные stdint/stddef (в glibc их тянул stdio). */
#include <stdint.h>
#include <stddef.h>
