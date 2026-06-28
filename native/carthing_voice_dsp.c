#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <speex/speex_preprocess.h>

#define TARGET_RATE 8000
#define SPEEX_FRAME_SIZE 80
#define MAX_OUTPUT_SAMPLES 4096
#define MAX_INPUT_FRAMES (MAX_OUTPUT_SAMPLES * 6)

typedef struct {
    SpeexPreprocessState *speex;
    int predictor;
    int index;
    int adpcm_initialized;
    int16_t mono[MAX_OUTPUT_SAMPLES];
} CarThingVoiceDsp;

static const int ima_index_table[16] = {
    -1, -1, -1, -1, 2, 4, 6, 8,
    -1, -1, -1, -1, 2, 4, 6, 8,
};

static const int ima_step_table[89] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
};

static int clamp16(int value) {
    if (value > 32767) {
        return 32767;
    }
    if (value < -32768) {
        return -32768;
    }
    return value;
}

void *carthing_voice_dsp_create(int noise_suppress_db) {
    CarThingVoiceDsp *ctx = calloc(1, sizeof(*ctx));
    int enabled = 1;
    int disabled = 0;

    if (ctx == NULL) {
        return NULL;
    }
    ctx->speex = speex_preprocess_state_init(SPEEX_FRAME_SIZE, TARGET_RATE);
    if (ctx->speex == NULL) {
        free(ctx);
        return NULL;
    }
    speex_preprocess_ctl(ctx->speex, SPEEX_PREPROCESS_SET_DENOISE, &enabled);
    speex_preprocess_ctl(ctx->speex, SPEEX_PREPROCESS_SET_AGC, &disabled);
    speex_preprocess_ctl(
        ctx->speex,
        SPEEX_PREPROCESS_SET_NOISE_SUPPRESS,
        &noise_suppress_db
    );
    return ctx;
}

void carthing_voice_dsp_destroy(void *opaque) {
    CarThingVoiceDsp *ctx = opaque;
    if (ctx == NULL) {
        return;
    }
    if (ctx->speex != NULL) {
        speex_preprocess_state_destroy(ctx->speex);
    }
    free(ctx);
}

const char *carthing_voice_dsp_backend(void *opaque) {
    (void)opaque;
    return "speexdsp";
}

int carthing_voice_dsp_process(
    void *opaque,
    const int16_t *input,
    int input_frames,
    int channels,
    int gain_q8,
    uint8_t *output,
    int output_capacity
) {
    CarThingVoiceDsp *ctx = opaque;
    int samples;
    int payload_size;
    int i;
    int start_predictor;
    int start_index;

    if (
        ctx == NULL || input == NULL || output == NULL ||
        input_frames <= 0 || input_frames > MAX_INPUT_FRAMES || channels <= 0
    ) {
        return -1;
    }

    samples = input_frames / 6;
    if (samples <= 0 || samples > MAX_OUTPUT_SAMPLES) {
        return -2;
    }
    payload_size = 4 + (samples + 1) / 2;
    if (output_capacity < payload_size) {
        return -3;
    }

    for (i = 0; i < samples; i++) {
        int64_t sum = 0;
        int source_frame;
        int channel;
        for (source_frame = 0; source_frame < 6; source_frame++) {
            int base = (i * 6 + source_frame) * channels;
            for (channel = 0; channel < channels; channel++) {
                sum += input[base + channel];
            }
        }
        ctx->mono[i] = (int16_t)clamp16(
            (int)((sum * gain_q8) / (6 * channels * 256))
        );
    }

    for (i = 0; i + SPEEX_FRAME_SIZE <= samples; i += SPEEX_FRAME_SIZE) {
        speex_preprocess_run(ctx->speex, &ctx->mono[i]);
    }

    if (!ctx->adpcm_initialized) {
        ctx->predictor = ctx->mono[0];
        ctx->index = 0;
        ctx->adpcm_initialized = 1;
    }
    start_predictor = ctx->predictor;
    start_index = ctx->index;
    output[0] = (uint8_t)(start_predictor & 0xFF);
    output[1] = (uint8_t)((start_predictor >> 8) & 0xFF);
    output[2] = (uint8_t)start_index;
    output[3] = 0;
    memset(output + 4, 0, payload_size - 4);

    for (i = 0; i < samples; i++) {
        int step = ima_step_table[ctx->index];
        int diff = (int)ctx->mono[i] - ctx->predictor;
        int code = 0;
        int delta = step >> 3;

        if (diff < 0) {
            code = 8;
            diff = -diff;
        }
        if (diff >= step) {
            code |= 4;
            diff -= step;
            delta += step;
        }
        if (diff >= (step >> 1)) {
            code |= 2;
            diff -= step >> 1;
            delta += step >> 1;
        }
        if (diff >= (step >> 2)) {
            code |= 1;
            delta += step >> 2;
        }

        ctx->predictor = clamp16(
            ctx->predictor + ((code & 8) ? -delta : delta)
        );
        ctx->index += ima_index_table[code];
        if (ctx->index < 0) {
            ctx->index = 0;
        } else if (ctx->index > 88) {
            ctx->index = 88;
        }
        output[4 + i / 2] |= (uint8_t)(code << ((i & 1) * 4));
    }

    return payload_size;
}
