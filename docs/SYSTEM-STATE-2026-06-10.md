# Состояние системы после 2026-06-10 — карта для Codex

Этот документ — актуальный «вход в проект» после большой сессии 2026-06-10.
Хронология и доказательства: `docs/session-2026-06-10-summary.md` + таблица в
`docs/dual-mode-test-plan-2026-06-10.md`. Запреты: `INVARIANTS.md` (ЧИТАТЬ ПЕРВЫМ).

## Что система УМЕЕТ (всё проверено на железе, всё в rootfs bake №3)

- **Play Now (дефолт)**: BLE-линк с iPhone постоянный (AMS/ANCS/CTS),
  метаданные/управление; classic к iPhone НЕ подключается, выхода в Control
  Center НЕТ. Колонка может быть прилипшей (standby) — iPhone не трогается.
- **Тумблер маршрута**: `echo connect > /run/carthing/route-cmd` →
  `connect_source(iPhone)` → выход «Car Thing» в CC за ~2.5 c.
  `echo disconnect` → graceful AVDTP teardown → iOS ставит музыку на паузу и
  мгновенно отдаёт маршрут (UX «выдернул наушники», reason 0x13, НЕ 0x08).
  Физкнопка/GUI вешаются на этот же механизм (орган — решение владельца).
- **Труба**: iPhone → Car Thing (A2DP Sink AAC/SBC) → Fosi (A2DP Source),
  сквозной AAC без транскодирования, `sent_to_speaker=True`, переживает
  паузу/Siri/треки (suspend ≠ teardown).
- **AVRCP-коммутатор**: сессия НА КАЖДОГО пира (`avrcp_sessions{}`), свой
  L2CAP-сервер на AVCTP PSM, маршрутизация по trust. iPhone и колонка живут
  одновременно. Backchannel: кнопки пульта Fosi → AMS-интент → iPhone.
- **Громкость**: iPhone → колонка (`SetAbsoluteVolume`, успех CONTROL-команд =
  `ResponseCode.ACCEPTED`). Обратное (Fosi→iPhone) на ZD3 невозможно — прошивка
  не экспортирует гейн пульта (доказано 4 механизмами + эталоном macOS);
  машинерия (форс-подписка VOLUME_CHANGED + notify + эхо-гашение) готова для
  честных колонок.
- **C1/SDS**: SDP-запись ServiceDiscoveryServer + ServiceDatabaseState
  (sha1-отпечаток записей) → iOS перечитывает SDP на каждом коннекте.
  **«Forget This Device» для SDP-правок больше не нужен.**
- **Classic-first CTKD** (лабораторный путь): гонка link-key устранена
  (poll keystore до 5 c), колонки в CTKD-ветку не попадают. ⚠️ ОСТАВЛЯЕТ LE
  СПЯЩИМ (iOS сам BLE не поднимает) → пользовательская пара ТОЛЬКО BLE-first.

## Где что лежит

**Репо** (`overlay/usr/lib/carthing/` → на устройстве `/usr/lib/carthing/`):
- `carthing_runtime.py` — вход; задачи: `_resume_bonded_classic_audio`
  (дозвон с ретраями 3/8/15 c, гейт после enroll колонки),
  `_pair_speaker_once` (headless enroll по `CARTHING_PAIR_SPEAKER`),
  `_route_command_watcher` (тумблер), `_complete_classic_first_ctkd`.
- `a2dp_bridge.py` — мост: SDP (включая SDS/C1), per-peer AVRCP,
  endpoint'ы AAC+SBC, труба (`forward_packet`), standby-цикл с backoff
  (12→300 c), volume-роутинг, graceful `disconnect_source`.
- `accessory_orchestrator.py` — dual-mode персона: pairing-фабрика
  (sc+bonding+ct2, LE раздаёт link key, BR/EDR — нет), видимость по фазам.
- `transfer_control.py` — backchannel колонка→источник.
- `vendor/bumble/` — v0.0.229 + НАШИ фиксы: l2cap (peer flush timeout;
  mode negotiation: counter UNACCEPTABLE_PARAMETERS вместо abort), hci
  (Write_Automatic_Flush_Timeout), smp/pairing (CT2). Защищено чекером.

**Устройство**: rootfs RO на eMMC; `/run/carthing-state` (ext4 p3 с журналом) =
keys.json + state.json — переживает прошивку rootfs и ребут; p1 остаётся boot FAT
и монтируется read-only как `/run/carthing-boot`; `/run/carthing/`
= логи. Dev-итерации: tar overlay → `/run/carthing-dual-mode-lab` (см. ниже).

## Как запускать / dev-цикл

Карантин Bumble действует (автостарта НЕТ — решение владельца не принято).
Запуск после ребута (из rootfs):

```sh
ssh root@172.16.42.77 'cd /usr/lib/carthing && env CARTHING_BUMBLE_QUARANTINE=0 \
  CARTHING_ALLOW_BUMBLE_RUN=1 CAR_THING_TRANSPORT=hci-socket:0 \
  CAR_THING_KEYSTORE=/run/carthing-state/carthing/keys.json \
  CAR_THING_LIB=/usr/lib/carthing/vendor CARTHING_GUI_ENABLE=0 \
  nohup python3 -B carthing_runtime.py > /run/carthing/runtime.log 2>&1 &'
```

Опциональные env: `CARTHING_CLASSIC_AUDIO_RECONNECT=1` (автодозвон classic на
старте — лаб-удобство, НЕ дефолт), `CARTHING_PAIR_SPEAKER=<MAC>` (one-shot
enroll колонки в режиме пары), `CAR_THING_AUTO_PAIRING=1` (взвести пару),
`CARTHING_PAIRING_PRIMARY=classic` (лабораторный classic-first).

Dev-правки: редактировать в репо → `python3 -m py_compile` →
`tar --exclude='__pycache__' -C overlay/usr/lib -cf - carthing | ssh ... 'tar -C
/run/carthing-dual-mode-lab -xf -'` → kill по PID из `ps` (busybox, pkill нет)
→ запуск из `/run/carthing-dual-mode-lab/carthing`. Валидировано → bake:
обновить `EXPECTED_RUNTIME_TREE_SHA1` в `scripts/bake-unified-runtime-rootfs.py`,
`scripts/check-bake-readiness.sh`, bake с
`--base-bundle artifacts/flash-python-full-final-20260605`, прошивка
`printf '\n' | CARTHING_FLASH_BUNDLE_DIR=<bundle> python3
scripts/flash-device1-rootfs-only.py` (устройство в burn mode 1b8e:c003).

## Наблюдаемость (НОВОЕ — обе стороны эфира)

- Наша сторона: `/run/carthing/*.log`; ВСЕ AVRCP-строки с `peer=<адрес>`.
- **Сторона iPhone** (профили Apple установлены, iOS 27):
  `uvx pymobiledevice3 syslog live` — живой bluetoothd DEBUG (фильтровать по
  `30:E3:D6|Car Thing`); PacketLogger (Additional Tools) → New iOS Trace →
  `.pklg` → `tshark -r` (поля `bthci_evt.*`, `btavdtp`, `btsmp`, `btsdp`).
  Эталонные трейсы: `16.pklg` (classic-first SSP+CTKD), `17.pklg`
  (graceful teardown) в `~/Downloads`.
- Урок: спор «наш баг vs железо» решается эталонным стеком (Mac/iOS).

## Известные хвосты (по приоритету)

1. Орган тумблера (физкнопка из 6 / GUI) и снятие карантина — решения владельца.
2. A1-остаток: SBC-ветка кодек-матрицы; mismatch-защита трубы.
3. A4 (trusted source после classic-first без рестарта), A5 (выбор dual-mode
   бонда при нескольких источниках).
4. B2/B6 (обратный порядок, радиус), D2-остаток (reboot-матрица), блок E.
5. C2–C9 (DID, EIR TX Power, sniff, тайминги — по `reference/apple-adg/`).
6. Загадка: один volume-шквал 03:10 со стороны iPhone (не влияет).
7. Потерянная строка «CTKD complete» в A3-цикле 4 при записанных ключах.

---

## ОБНОВЛЕНИЕ (вечер 2026-06-10): карантин СНЯТ, автостарт работает

Раздел «Как запускать» выше частично устарел: ручной запуск больше НЕ нужен.

- Автостарт: inittab → init-wrapper → `/etc/init.d/disabled-S50-carthing-remote`
  (имя историческое; это АКТИВНЫЙ стартер с supervisor-петлёй и полным
  продуктовым env). S60 не существует (retired).
- Рубильник: `touch /run/carthing-state/carthing/no-autostart && reboot`.
- Единый реестр доверенных: `CARTHING_TRUSTED_DEVICES=.../state.json` (запечён;
  легаси trusted-devices.json вызывал двойное хранилище и потерю колонок).
- Лог runtime: `/run/carthing/carthing-remote.log` (контракт defaults).
- Замер: питание → ~49 c → iPhone (AMS) + Fosi (standby+stream+AVRCP) сами.
- Ручная команда из раздела выше остаётся для лаборатории (сначала
  `kill` supervisor по pid-файлу `/run/carthing/media-remote-supervisor.pid`).
