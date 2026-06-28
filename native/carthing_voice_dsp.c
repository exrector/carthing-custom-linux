#include <stdint.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <speex/speex_preprocess.h>
#include <opus/opus.h>

#define MAX_OUTPUT_SAMPLES 4096
#define MAX_INPUT_FRAMES (MAX_OUTPUT_SAMPLES * 6)

typedef struct {
    SpeexPreprocessState *speex;
    OpusEncoder *opus;
    int predictor;
    int index;
    int adpcm_initialized;
    int target_rate;
    int decimation;
    int speex_frame_size;
    int channel_count;
    int channel_rms[4];
    int channel_peak[4];
    int mono_pre_rms;
    int mono_post_rms;
    int mono_peak;
    int clipped_samples;
    int codec;
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

void *carthing_voice_dsp_create(
    int noise_suppress_db,
    int target_rate,
    int codec,
    int bitrate
) {
    CarThingVoiceDsp *ctx = calloc(1, sizeof(*ctx));
    int enabled = 1;
    int disabled = 0;

    if (ctx == NULL) {
        return NULL;
    }
    if (target_rate != 8000 && target_rate != 16000) {
        free(ctx);
        return NULL;
    }
    ctx->target_rate = target_rate;
    ctx->codec = codec;
    ctx->decimation = 48000 / target_rate;
    ctx->speex_frame_size = target_rate / 100;
    ctx->speex = speex_preprocess_state_init(
        ctx->speex_frame_size,
        ctx->target_rate
    );
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
    if (codec == 1) {
        int opus_error = OPUS_OK;
        if (target_rate != 16000) {
            speex_preprocess_state_destroy(ctx->speex);
            free(ctx);
            return NULL;
        }
        ctx->opus = opus_encoder_create(
            target_rate,
            1,
            OPUS_APPLICATION_VOIP,
            &opus_error
        );
        if (ctx->opus == NULL || opus_error != OPUS_OK) {
            speex_preprocess_state_destroy(ctx->speex);
            free(ctx);
            return NULL;
        }
        opus_encoder_ctl(
            ctx->opus,
            OPUS_SET_APPLICATION(OPUS_APPLICATION_VOIP)
        );
        opus_encoder_ctl(ctx->opus, OPUS_SET_BITRATE(bitrate));
        opus_encoder_ctl(ctx->opus, OPUS_SET_VBR(1));
        opus_encoder_ctl(ctx->opus, OPUS_SET_SIGNAL(OPUS_SIGNAL_VOICE));
        opus_encoder_ctl(ctx->opus, OPUS_SET_COMPLEXITY(5));
        opus_encoder_ctl(
            ctx->opus,
            OPUS_SET_BANDWIDTH(OPUS_BANDWIDTH_WIDEBAND)
        );
        opus_encoder_ctl(ctx->opus, OPUS_SET_DTX(0));
    } else if (codec != 0) {
        speex_preprocess_state_destroy(ctx->speex);
        free(ctx);
        return NULL;
    }
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
    if (ctx->opus != NULL) {
        opus_encoder_destroy(ctx->opus);
    }
    free(ctx);
}

const char *carthing_voice_dsp_backend(void *opaque) {
    CarThingVoiceDsp *ctx = opaque;
    return ctx != NULL && ctx->codec == 1
        ? "speexdsp+opus"
        : "speexdsp+ima_adpcm";
}

int carthing_voice_dsp_target_rate(void *opaque) {
    CarThingVoiceDsp *ctx = opaque;
    return ctx == NULL ? 0 : ctx->target_rate;
}

int carthing_voice_dsp_get_stats(
    void *opaque,
    int32_t *values,
    int capacity
) {
    CarThingVoiceDsp *ctx = opaque;
    int i;
    if (ctx == NULL || values == NULL || capacity < 13) {
        return -1;
    }
    values[0] = ctx->channel_count;
    for (i = 0; i < 4; i++) {
        values[1 + i] = ctx->channel_rms[i];
        values[5 + i] = ctx->channel_peak[i];
    }
    values[9] = ctx->mono_pre_rms;
    values[10] = ctx->mono_post_rms;
    values[11] = ctx->mono_peak;
    values[12] = ctx->clipped_samples;
    return 13;
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
    int64_t channel_sum_squares[4] = {0, 0, 0, 0};
    int64_t mono_sum_squares = 0;

    if (
        ctx == NULL || input == NULL || output == NULL ||
        input_frames <= 0 || input_frames > MAX_INPUT_FRAMES || channels <= 0
    ) {
        return -1;
    }

    samples = input_frames / ctx->decimation;
    if (samples <= 0 || samples > MAX_OUTPUT_SAMPLES) {
        return -2;
    }
    payload_size = 4 + (samples + 1) / 2;
    if (output_capacity < payload_size) {
        return -3;
    }

    ctx->channel_count = channels > 4 ? 4 : channels;
    memset(ctx->channel_rms, 0, sizeof(ctx->channel_rms));
    memset(ctx->channel_peak, 0, sizeof(ctx->channel_peak));
    ctx->mono_peak = 0;
    ctx->clipped_samples = 0;
    for (i = 0; i < input_frames; i++) {
        int channel;
        for (channel = 0; channel < ctx->channel_count; channel++) {
            int value = input[i * channels + channel];
            int magnitude = value < 0 ? -value : value;
            channel_sum_squares[channel] += (int64_t)value * value;
            if (magnitude > ctx->channel_peak[channel]) {
                ctx->channel_peak[channel] = magnitude;
            }
        }
    }
    for (i = 0; i < ctx->channel_count; i++) {
        ctx->channel_rms[i] = (int)sqrt(
            (double)channel_sum_squares[i] / input_frames
        );
    }

    for (i = 0; i < samples; i++) {
        int64_t sum = 0;
        int source_frame;
        int channel;
        for (
            source_frame = 0;
            source_frame < ctx->decimation;
            source_frame++
        ) {
            int base = (
                i * ctx->decimation + source_frame
            ) * channels;
            for (channel = 0; channel < channels; channel++) {
                sum += input[base + channel];
            }
        }
        int mixed = (int)(
            (sum * gain_q8)
            / (ctx->decimation * channels * 256)
        );
        int magnitude;
        if (mixed > 32767 || mixed < -32768) {
            ctx->clipped_samples++;
        }
        mixed = clamp16(mixed);
        magnitude = mixed < 0 ? -mixed : mixed;
        if (magnitude > ctx->mono_peak) {
            ctx->mono_peak = magnitude;
        }
        mono_sum_squares += (int64_t)mixed * mixed;
        ctx->mono[i] = (int16_t)mixed;
    }
    ctx->mono_pre_rms = (int)sqrt((double)mono_sum_squares / samples);

    for (
        i = 0;
        i + ctx->speex_frame_size <= samples;
        i += ctx->speex_frame_size
    ) {
        speex_preprocess_run(ctx->speex, &ctx->mono[i]);
    }
    mono_sum_squares = 0;
    for (i = 0; i < samples; i++) {
        int value = ctx->mono[i];
        mono_sum_squares += (int64_t)value * value;
    }
    ctx->mono_post_rms = (int)sqrt((double)mono_sum_squares / samples);

    if (ctx->codec == 1) {
        return opus_encode(
            ctx->opus,
            ctx->mono,
            samples,
            output,
            output_capacity
        );
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
