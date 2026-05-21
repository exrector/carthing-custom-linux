# Car Thing microphone capture test - 2026-05-21

## Context

Device was reachable over USB/NCM at `172.16.42.77`. The goal was to verify the
on-device microphones by making a real capture from the live system and listening
to the resulting audio on the Mac.

The target rootfs did not include `arecord`, `aplay`, `amixer`, `tinycap`,
`tinymix`, `ffmpeg`, or `sox`. It did expose an ALSA capture PCM device through
the kernel:

```text
/dev/snd/controlC0
/dev/snd/pcmC0D0c
/dev/snd/timer
```

ALSA card and PCM identity:

```text
0 [AMLAUGESOUND]: AML-AUGESOUND
00-00: PDM-dummy-alsaPORT-pdm dummy-0 : : capture 1
```

Kernel logs showed the Amlogic PDM path was initialized:

```text
aml_pdm_platform_probe pdm filter mode from dts:1
aml_pdm_probe
aml_pdm_dai_probe
aml_pdm_pcm_new
asoc-aml-card auge_sound: dummy <-> ff642000.audiobus:pdm mapping ok
```

## Capture method

A temporary aarch64 utility, `carthing_miccap`, was cross-compiled on the Mac
against the Buildroot sysroot kernel UAPI headers. It used direct ALSA PCM
ioctls against `/dev/snd/pcmC0D0c`, so it did not require `alsa-lib` on the
device.

The utility was copied to `/run/carthing_miccap`, used for the test, and then
removed from `/run`.

## PCM capabilities observed

The capture PCM accepted interleaved capture and reported:

```text
access_rw_interleaved=1
fmt_s16_le=1 fmt_s24_le=1 fmt_s32_le=1
sample_bits=16..32 integer=1 empty=0
frame_bits=16..512 integer=1 empty=0
channels=1..16 integer=1 empty=0
rate=8000..96000 integer=0 empty=0
period_size=1..131072 integer=1 empty=0
periods=2..1024 integer=1 empty=0
buffer_size=2..262144 integer=1 empty=0
info=0xc0103 msbits=0 rate_num=0 rate_den=0 fifo=0
```

## Stereo test

Recorded 5 seconds as S16LE, 16 kHz, 2 channels:

```text
/run/mic-test-16k-stereo.wav
size: 320044 bytes
sha256: 26d4a2dfec69e4652518a2c3d1e81b181fa7670b4b19526e864aa2e721d483f0
```

Mac-side `ffprobe`:

```text
Duration: 00:00:05.00, bitrate: 512 kb/s
Audio: pcm_s16le, 16000 Hz, 2 channels, s16, 512 kb/s
```

Mac-side `sox stat`:

```text
Samples read:            160000
Length (seconds):      5.000000
Maximum amplitude:     0.031525
Minimum amplitude:    -0.008911
RMS     amplitude:     0.002756
Volume adjustment:       31.721
```

Per-channel stereo RMS:

```text
ch1 RMS amplitude: 0.002649
ch2 RMS amplitude: 0.002859
```

The original and normalized stereo files were pulled to:

```text
~/Downloads/carthing-mic-tests/mic-test-16k-stereo.wav
~/Downloads/carthing-mic-tests/mic-test-16k-stereo-normalized.wav
```

Both were played back on the Mac with `afplay`.

## Four-channel test

Because the PCM advertised multiple channels and the hardware likely has a
microphone array, a 4-channel test was recorded: S16LE, 16 kHz, 4 channels,
3 seconds.

```text
/run/mic-test-16k-4ch.wav
size: 384044 bytes
sha256: e2021d0d4514380124f92dd71679c183de472a4e756c18cecf77f9d267aafa16
```

Mac-side `ffprobe`:

```text
Duration: 00:00:03.00, bitrate: 1024 kb/s
Audio: pcm_s16le, 16000 Hz, 4 channels, s16, 1024 kb/s
```

Per-channel `sox stat` results:

```text
ch1 RMS amplitude: 0.002594, max: 0.025757, min: -0.004395
ch2 RMS amplitude: 0.002937, max: 0.031372, min: -0.005005
ch3 RMS amplitude: 0.003022, max: 0.030731, min: -0.005005
ch4 RMS amplitude: 0.003055, max: 0.030182, min: -0.005585
```

All four channels were non-zero and close in level. This strongly suggests that
the PDM capture path exposes four active microphone channels, matching the
working hypothesis that the device has a 4-microphone array.

Pulled and derived files on the Mac:

```text
~/Downloads/carthing-mic-tests/mic-test-16k-4ch.wav
~/Downloads/carthing-mic-tests/mic-test-16k-4ch-downmix-normalized.wav
~/Downloads/carthing-mic-tests/mic-test-16k-ch1-normalized.wav
~/Downloads/carthing-mic-tests/mic-test-16k-ch2-normalized.wav
~/Downloads/carthing-mic-tests/mic-test-16k-ch3-normalized.wav
~/Downloads/carthing-mic-tests/mic-test-16k-ch4-normalized.wav
```

The downmix and individual normalized channels were played on the Mac with
`afplay`.

## Cleanup

Temporary files were removed from the device:

```text
/run/carthing_miccap
/run/mic-test-16k-stereo.wav
/run/mic-test-16k-4ch.wav
```

Temporary local build files were removed:

```text
/private/tmp/carthing_miccap
/private/tmp/carthing_miccap.c
```

The pulled WAV files were intentionally kept under
`~/Downloads/carthing-mic-tests/` for listening and comparison.

## Next useful test

Record a longer 4-channel sample while producing a sharp sound near each edge of
the device in sequence. That should map physical microphone positions to ALSA
channels 1-4 and confirm whether the channels correspond to four separate
microphones rather than duplicated or post-processed paths.
