# Аудио-транскод и line-out на Car Thing (результат)

**Что это:** у Car Thing по умолчанию **нет тракта воспроизведения** — только PDM-микрофон (capture). Здесь онбордовый ЦАП **T9015** заведён на аналоговый **line-out**, и поверх построен полный тракт: A2DP-поток iPhone (**SBC/AAC**) декодируется **прямо на устройстве** в реальном времени и выводится в аналог. То есть устройство без playback-драйвера заставили играть звук.

Готовый результат: рабочий тракт декод→ЦАП + исходники декодеров + DTS-патчи + таймлайн.

## Что доказано (end-to-end live)

- **T9015 DAC заведён** через bare-ioctl ALSA-движок (`audio_out_t9015.py`) + DTS-патчи (`T9015-PLAYBACK-DTS-PATCHES.md`). Аналоговый line-out работает.
- **SBC-декодер с нуля** — bit-exact с ffmpeg, ~**1.7x realtime** на устройстве (`sbc_decoder.py` + `sbc_synth.so`).
- **Reference libsbc** скомпилирован freestanding под устройство — энкодер **x70 realtime** (`libsbc.so`).
- **Helix AAC** декодер (`helix_aac_decoder.py` + `libhelixaac.so`).
- **Line-out chain LIVE end-to-end:** SBC iPhone → декод → **запущенный T9015 ЦАП**.
- **Zero-config transcode** — это «закон проекта»: транскод включается без настройки.

## Архитектура тракта

```
iPhone A2DP (SBC/AAC)
   → приём (a2dp_bridge, см. ../bluetooth-router)
   → декод on-device: sbc_decoder / helix_aac_decoder
   → AudioLocalSink (очередь + player-поток + сокет-протокол)
   → T9015 bare-ioctl ALSA engine → аналоговый line-out
```

## Исходники (рабочий тракт)

| Файл | Роль |
|---|---|
| `audio_out_t9015.py` | bare-ioctl ALSA движок для ЦАП T9015 (line-out) |
| `sbc_decoder.py` + `sbc_synth.so` | SBC-декодер (bit-exact с ffmpeg) |
| `libsbc.so` | reference libsbc (freestanding) |
| `helix_aac_decoder.py` + `libhelixaac.so` | AAC-декодер (Helix) |
| `aac_to_sbc_transcoder.py` | транскод AAC→SBC |
| `audio_local_sink.py` + `local_sink_client.py` | локальный sink: очередь, player-поток, сокет |

## Документы

| Док | Что |
|---|---|
| `docs/T9015-PLAYBACK-DTS-PATCHES.md` | как заведён ЦАП T9015 (DTS-патчи) — ключевой результат |
| `docs/TIMELINE-git.md` | хронология «chip work» (floors 1-5, line-out LIVE, SBC bit-exact) из git |
| `docs/ios-dual-mode-audio-route-2026-06-05.md` | маршрут аудио iOS dual-mode |

## Значимость
Устройство, у которого «из коробки» нет вывода звука, превращено в аналоговый аудиоинтерфейс с on-device декодом A2DP. Декодеры — свои/портированные, всё в realtime, без облака и без пересжатия с потерей.
