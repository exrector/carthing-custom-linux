# Эксперименты Car Thing — результаты

Здесь — **дистиллированные результаты всех экспериментов** над Spotify Car Thing (Superbird): что было сделано, что вскрыто, что заработало. Не сырые дампы и не build-балласт — а готовые результаты, данные тестов, воспроизводимые инструменты и объяснение, **как этим пользоваться дальше в коде**.

Это история того, как закрытое устройство вскрыли глубже, чем любой публичный проект: от голого железа со скрытым userspace Spotify до своего Linux, медиа-роутера, аудиоинтерфейса и вскрытого MFi-чипа, которого нет ни у кого.

## Достижения

| Эксперимент | Суть результата |
|---|---|
| [`mfi-chip/`](mfi-chip/) | **Первый clean-room доступ к запертому Apple MFi auth-чипу** Car Thing. Протокол ACP 3.0 вскрыт, живьём доказаны извлечение сертификата (PKCS#7) и подпись challenge; сверху — clean-room iAP2-стек. Реальные запросы/ответы + рабочий инструмент. |
| [`hardware-map/`](hardware-map/) | **Полная карта чипов** платы (I2C-сканы, DTB, dmesg): touch, акселерометр, **USB-C мультиплексор MAX20332 (без драйвера, управляем из userspace)**, ALS/proximity, MFi. Что есть, что спит, что доступно. |
| [`custom-linux-bringup/`](custom-linux-bringup/) | **Свой Buildroot-Linux** взамен закрытого userspace Spotify (стоковый bootloader/kernel/dtb переиспользованы). Фундамент, 101 коммит. Воспроизводимый build-рецепт. |
| [`bluetooth-router/`](bluetooth-router/) | Car Thing как **BT медиа-роутер**: dual-mode (BLE+A2DP) на одном MAC, A2DP-мост, per-peer AVRCP-коммутатор, граф маршрутов. На Bumble, без BlueZ. |
| [`audio-transcode/`](audio-transcode/) | **Звук на устройстве без playback-драйвера**: заведён ЦАП T9015 (line-out), свой SBC-декодер (bit-exact, 1.7x realtime) + Helix AAC → A2DP iPhone декодируется и играет в аналог. |
| [`gui-compositor/`](gui-compositor/) | **GUI PIL→DRM** напрямую (без LVGL/веб-киоска): модульный compositor, тема «Терминал», нативный поворот кадра, рендер снят с BT-петли. |
| [`ancs-reconnect-and-identity/`](ancs-reconnect-and-identity/) | **Factory-identity из efuse** (имя «SN: …», переживает битый state) + стабильный reconnect/visibility (HID-пара переживает cold boot). |
| [`usb-audio-uac/`](usb-audio-uac/) | **USB Audio gadget** (UAC через configfs) + управляемый USB-профиль (NCM/storage/audio) + macOS-снэпшот. |

## Как читать
Каждая папка самодостаточна: `README.md` = достижение + данные/результаты + как пользоваться; рядом — инструменты/исходники, доки-доказательства, reference. Балласт (клоны buildroot, гигабайтные образы, build-output) сюда намеренно не клался — он воспроизводим и к истории не относится.
