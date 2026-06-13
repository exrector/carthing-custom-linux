#pragma once

/* Minimal C-only Helix configuration for Car Thing.
 *
 * The upstream Arduino wrapper ships a C++/Arduino-oriented ConfigHelix.h.
 * The decoder core only needs feature flags and allocator/logging constants,
 * so keep this shim deliberately small and freestanding.
 */

#define SYNCH_WORD_LEN 4
#define HELIX_CHUNK_SIZE 1024

#define AAC_MAX_OUTPUT_SIZE (1024 * 8)
#define AAC_MAX_FRAME_SIZE 2100
#define AAC_MIN_FRAME_SIZE 1024

/* Keep first pass AAC-LC only. SBR can be enabled later if a real captured
 * stream proves that iOS negotiates HE-AAC rather than AAC-LC.
 */
#undef HELIX_FEATURE_AUDIO_CODEC_AAC_SBR

#define HELIX_LOGGING_ACTIVE 0
#define HELIX_LOG_LEVEL 0
