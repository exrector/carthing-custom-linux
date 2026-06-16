# Buildroot overlay для UAC2 audio bridge

Подготовлено Claude (Opus 4.7) для Codex, 2026-05-28.
Связано с [[carthing-claude-usb-audio-target-20260528]].

## Что нужно добавить в Buildroot config

Чтобы `carthing-uac2-bridge.sh` работал, в rootfs нужны:

```
BR2_PACKAGE_ALSA_UTILS=y
BR2_PACKAGE_ALSA_UTILS_ALSALOOP=y       # КРИТИЧНО — основной инструмент моста
BR2_PACKAGE_ALSA_UTILS_APLAY=y          # для отладки + проверки карт
BR2_PACKAGE_ALSA_UTILS_AMIXER=y         # для регулировки громкости T9015
BR2_PACKAGE_ALSA_UTILS_ALSACTL=y        # для сохранения mixer state
BR2_PACKAGE_ALSA_LIB=y                  # подтянется автоматически
```

Опционально (для PDM 4-канал validation без alsa-utils весов):

```
BR2_PACKAGE_TINYALSA=y                  # tinyplay/tinycap, ~80KB вместо ~1MB
```

## Размер

`alsa-utils` целиком + `alsa-lib` ~ 1.5–2 MB в rootfs. Текущий rootfs 512M, занято ~51M (acceptance 25.05), есть масса места.

`tinyalsa` ~ 80–150 KB. Если бюджет жёсткий — взять только её, но тогда `alsaloop` нет и bridge надо переписать через `tinyplay | tinycap` pipe. Не рекомендую — alsaloop умнее с jitter.

## Куда положить bridge-скрипт

```
package/carthing-uac2-bridge/
├── carthing-uac2-bridge.mk        # минимальный Buildroot package
└── carthing-uac2-bridge.sh        # сам скрипт → /usr/libexec/carthing/
```

Или просто через rootfs overlay:

```
board/carthing/rootfs-overlay/usr/libexec/carthing/carthing-uac2-bridge
```

(права 0755, owner root:root.)

## Альтернатива без Buildroot изменений

Если переcборка rootfs не вписывается в текущую сессию — `alsaloop` можно скачать готовый aarch64 static (например, из Alpine `alsa-utils` apk: `apk fetch alsa-utils --arch aarch64`) и положить в overlay поверх rootfs.img. Но это costlier чем добавить BR2 флаг.
