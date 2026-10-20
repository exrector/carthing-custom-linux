# PENDING-BAKE — что нужно запечь в следующий образ

Сюда пишем всё что изменено на живом устройстве вручную и ещё не запечено в rootfs.img.
Перед каждым бейком — пройтись по списку и убедиться что всё внесено в overlay.

---

## Ожидает бейка

*(пусто после локального bake `flash-bake-unified-stable-20260618-103948`; устройство не прошивалось этим bundle)*

---

## Запечено (история)

| Дата | Что изменено | Как запечено |
|------|-------------|--------------|
| 2026-06-17 | GE2D userspace (`ge2d.py`, `ge2d_test.py`) + native AAC/SBC libs (`libhelixaac.so`, `libsbc.so`, `sbc_synth.so`) | `tools/bake-rootfs.py` → `image/rootfs.img`, then sha256 `13b2b14f...` |
| 2026-06-17 | Product mount/debug cleanup: `S03-runtime-state` only, vfat `noatime,nodiratime,flush`, release debug profile `quiet`, HTTP/telnet/reverse-agent off by default | `tools/bake-rootfs.py` → `image/rootfs.img`, then sha256 `13b2b14f...` |
| 2026-06-17 | Boot profiling markers + precompiled Python bytecode (`342` `.pyc` files) + ранний DRM/GUI home surface перед BLE/Bumble init | `tools/bake-rootfs.py` → `image/rootfs.img`, latest sha256 `b638d769...` |
| 2026-06-17 | `source/base-bundle` hardware baseline repaired: old bootfs `7977c311...`, dirty-FAT GE2D bootfs `2ff2159a...`, intermediate bootfs `28f4b24a...`, and Android-bootargs GE2D bootfs `957f91c3...` replaced with clean Linux/CarThing bootfs `6e99a75c...`; bake rejects all stale hashes | `source/base-bundle/SHA256SUMS` + `tools/bake-rootfs.py` guard |
| 2026-06-17 | Ядро с GE2D (`CONFIG_AMLOGIC_MEDIA_GE2D=y`) — `/dev/ge2d` теперь есть; `bootargs.txt` cleaned from Android/vendor params | `image/bootfs.bin` обновлён и FAT-cleaned, sha256 `6e99a75c` |
| 2026-06-17 | Пароль root = `carthing` | `overlay/etc/shadow` создан с SHA-512 хэшем; `bake-rootfs.py` копирует его автоматически |
| 2026-06-17 | Логотип при загрузке — наш (вождь, 480×800 RGB565), normal boot slot `bootup_spotify` | `image/bootlogos.bin` + `tools/flash.py` пишет в сектор 319488 при прошивке |
| 2026-06-17 | BT-бонды не переносятся между устройствами | `bake-rootfs.py` вычищает `/var/lib/carthing-state` при каждом бейке |
| 2026-06-17 | Mode-aware resource policy: `resource_policy.py`, CPU governor diagnostics, optional `S11-zram`, runtime-state `resource_policy`, ALS/proximity diagnostics, and safe-unplug через центральный Play Now teardown | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260617-235414`, rootfs sha256 `362c4290d37cb7a5b1a93c2def85d9c0bd4d504487f7cfaa943bc327535ec17e`, runtime tree sha1 `e3e456c79ad0712a3c54549b71acd97dc4e7b6b1` |
| 2026-06-18 | Route-load/manual-background-policy: route-scoped Fosi standby, Play Now releases speaker ACL, periodic `LinkManager` polling disabled, `speaker_scan` manual/event-driven, proof script `tools/route-load-proof.sh`, iPhone stickiness preserved | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-013904`, rootfs sha256 `f5b6b1994c45174fef66d8947b0dd49679ebebe93bf70f5d7e545a512cbfb4ac`, runtime tree sha1 `856683dc1506cab30070c0229ca44aef1330ed48`; proof `docs/ROUTE-LOAD-PROOF-2026-06-18.md` |
| 2026-06-18 | Commutator snapshot standby: one-shot trusted-output scan on Коммутатор entry, hold all found online outputs, Play Now clears all external output footprints, Route-view mode/status line, external outputs dimmed in Play Now | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-015815`, rootfs sha256 `174ad69defe7a2edf4ed857ef61cf513e90b81766c2769109de2268fae2ed589`, runtime tree sha1 `1dd0d1d9ab0e2cdad4662c665eb2caeee3487b61`; proof `artifacts/route-load-20260618-015708/proof.json` |
| 2026-06-18 | Source-first gentle Play Now teardown: when leaving Коммутатор, close iPhone/source AVDTP stream/signaling before suspending/closing receiver outputs and releasing speaker ACLs | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-102714`, rootfs sha256 `713cfc81bccf9f53ad83ac7c6360f144a3bdd51f34934daaac695d9b9a51a8a2`, runtime tree sha1 `c7899528cc75dfaf0b97e1780de72595779b4a83`; live deploy verified source ACL closes before Play Now resource teardown, active-RTP graceful-close proof still needs Fosi + playback |
| 2026-06-18 | Play Now incoming-output gate: trusted speaker-owned Classic/AVCTP/AVDTP surfaces are rejected outside Коммутатор snapshot/selected-output ownership, preventing Fosi from self-attaching while GUI shows Play Now; iPhone source stickiness preserved | `tools/bake-rootfs.py` → `flash-bake-unified-stable-20260618-103948`, rootfs sha256 `6b13a8de1aa5e58e6f564d8088b724cb613f55428bb89f8edd663171fb7c1044`, runtime tree sha1 `70fca5213c2c3b23df05307f1d6aa27dc2de520f`; live deploy verified Play Now keeps Fosi/Maedhawk disconnected while iPhone AMS/ANCS/CTS stay active |

## 2026-07-01 — Ожидает следующего бейка

- Опциональная Pac-Man-анимация заставки с persisted-настройкой, обновлённый
  компактный экран настроек и runtime tree sha1
  `8ad251f840b5bd639cd2daf0d19b5e7a7497bf7c`. Изменения доставлены на живое
  устройство через `tools/deploy`, проверены по SHA-256 и bake-readiness, но
  пока не записаны в `rootfs.img`.

---

## 2026-10-20 — переполнение p1 журналом событий (Claude)

**Симптом (после ~4 мес. работы):** не подключается к iPhone, не публикует трек, не ищет iPhone.

**Корень:** `connection-events.jsonl` без ротации дорос до 17M и 2026-08-26 забил p1-FAT (32M, там же Image/dtb) на 100%.
С этого дня `state.json`/`settings`/`keys.json` не сохранялись (ENOSPC). После перепаривания на boot 2026-10-18
Bumble: `!!! error while storing keys` → у iPhone новый LTK, у Car Thing старый → бесконечный цикл
`LE connected encrypted=False → requesting pairing → disconnect reason=61 (MIC failure)`, ~48k раз за 41ч.
Дополнительно: `/run/carthing/carthing-remote.log` (tmpfs/RAM) без лимита — 25M за 41ч.

**Сделано на живом QN19 (без reboot, rootfs не трогали):** журнал усечён до 2000 строк (бэкап:
`carthing-device-backups/journal-overflow-20261020/`), p1 = 50%; runtime перезапущен; временный сторож
`/run/carthing/log-guard.sh` (до reboot) режет журнал >2M и лог >4M.

**В overlay к следующему bake:**
- `usr/lib/carthing/connection_journal.py` — ротация в одно поколение `.1`, лимит 512K (env `CARTHING_CONNECTION_JOURNAL_MAX_BYTES`).
- `etc/init.d/disabled-S50-carthing-remote` — фоновое усечение лога runtime >4M до 20000 строк.

**Удалённый доступ:** QN19 по USB в NAS UGREEN DXP2800 (`ugreen.tailb25627.ts.net`, Tailscale SSH root).
UGOS не грузит `cdc_ncm` сам: `modprobe cdc_ncm; ip link set usb0 up; ip addr add 172.16.42.1/24 dev usb0`
(не persistent). Вход: `ssh -i ~/.ssh/id_carthing -J root@100.65.216.72 root@172.16.42.77`.

### 2026-10-20 (продолжение) — дребезг энкодера громкости

После перепаривания (ключи сохранились, reason=61 ушёл) проявился дребезг ручки: ~25% тиков при вращении
приходят с неверным знаком через 41–51мс (= обычный интервал тиков 50мс) — похоже на износ/грязь одного
квадратурного контакта. iPhone часть таких +/- склеивает, а локальная шкала считает все → шкала ≠ реальной громкости.

- overlay `usr/lib/carthing/input_handler.py`: антидребезг — тик против текущего направления быстрее 120мс
  отбрасывается (окно скользит). env `CARTHING_ENCODER_REVERSAL_MS` (0 = выкл). Отброшенные пишутся в лог как `dropped (bounce)`.
- На живом QN19 применено без записи в rootfs: `mount --bind /run/carthing/hotfix/input_handler.py /usr/lib/carthing/input_handler.py`
  + рестарт runtime. Слетает при reboot — до bake.
- Аппаратно: можно попробовать очиститель контактов (DeoxIT) в энкодер.

**ОТКАТ (2026-10-20 14:13):** антидребезг энкодера и «свежая» синхронизация шкалы владелец забраковал — стало хуже,
чем до вмешательства. Bind-mount'ы сняты, на QN19 и в overlay возвращён исходный код
`input_handler.py`, `ams_client.py`, `iphone_service.py`, `runtime_model.py`, `gui_controller.py`.
В bake остаются только ротация журнала и лимит лога runtime.

### 2026-10-20 14:22 — громкость: iPhone перестал присылать AMS volume после команд с ручки

Июньские логи: iPhone слал PlayerAttributeVolume непрерывно (шаг 1%). Сегодня (iPhone, вероятно iOS 27 beta):
изменения с самого iPhone приходят, а после команд vol_up/vol_down с ручки — почти нет (34 команды → 2 значения).
Фикс в overlay `usr/lib/carthing/ams_client.py`: через 0.3с после последней команды громкости — повторная запись
подписки Player (name+playback+volume). После этого поток уведомлений восстановился: iPhone шлёт громкость на каждый тик,
шкала показывает значение iPhone. На QN19 применено bind-mount'ом (до reboot).

### 2026-10-20 14:32 — фильтр энкодера (по требованию владельца, после фикса AMS)

overlay `usr/lib/carthing/input_handler.py`: (1) пока ручка крутится, направление зафиксировано, тики против
направления в течение 300мс отбрасываются; (2) разворот после паузы откладывается на 250мс — если сразу пришёл тик
старого направления, это дребезг (по логам: при медленном вращении первым часто приходит ложный тик, через ~60мс
правильный). env: CARTHING_ENCODER_LOCK_MS / CARTHING_ENCODER_HOLD_MS. На записанных тиках: 161 → ~21 разворотов
внутри жестов (остаток — реальные развороты). На QN19 — bind-mount до reboot. GUI не менялся.

### 2026-10-20 14:35 — ЗАПЕЧЕНО

- Живой QN19: `tools/deploy` (через NAS jump) записал в rootfs p2 `ams_client.py`, `input_handler.py`,
  `connection_journal.py`, `etc/init.d/disabled-S50-carthing-remote` — md5 сверены, rootfs снова ro, переживает reboot.
  Bind-mount'ы и временный log-guard сняты. Перепрошивка/Maskrom не понадобились, BT-ключи на p1 целы.
- Образ: `tools/bake-rootfs.py` → `image/rootfs.img` sha256 `bdfd7b31…`, runtime tree sha1 `31c4708b…`.
  Старый rootfs `b638d769…` → `image/archive-20261020-pre-encoder/`.
- Guard bootfs в bake-rootfs.py обновлён на фактический `f01e3078…` (bootfs 2026-06-18 с новым dtb; сверен
  по md5 с живым p1). Прежний `6e99a75c…` в SHA256SUMS был устаревшей записью.
- ВНИМАНИЕ: полная прошивка `tools/flash.py` перезапишет p1 → сотрёт BT-ключи → потребуется перепаривание iPhone.

### 2026-10-20 14:56 — убрана задержка энкодера

Пользователь сообщил: после достижения максимума при немедленном развороте вниз команды начинали действовать только с заметной задержкой.

**Причина найдена в добавленном нами input-фильтре:** каждый отброшенный встречный тик обновлял `enc["ts"]`, тем самым продлевая блокировку направления во время всего потока. После прекращения встречных тиков фильтр ждал ещё до 300 мс, затем удерживал первый тик разворота 250 мс. Получалось до ~550 мс тишины; подтверждение разворота могло сразу породить две AMS-команды. Это и давало «не убавляется, потом скачком». Предыдущее объяснение износа контактов по интервалам тиков было недоказанным.

**Исправление:** полностью убран user-space direction-lock/hold. На устройстве снова используется исходный `input_handler.py` (совпадает с `ca8069a` до фильтра), который сразу передаёт каждый REL_HWHEEL тик в GUI. Live-деплой `tools/deploy ... --restart` завершился успешно 14:56; runtime PID 1665 поднялся, iPhone подключён. AMS refresh после volume-команд оставлен.

**Проверка архитектуры энкодера:** `/sys/devices/platform/rotary@0/driver` = Linux `rotary-encoder`; device-tree `compatible="rotary-encoder"`, `linux,axis=6` (`REL_HWHEEL`), `rotary-encoder,steps-per-period=2` (half-period). Значит приложение получает уже декодированные kernel events. По временным интервалам этих событий нельзя заключать, что каждый быстрый обратный тик — электрический bounce или износ; удалённый фильтр был ошибочен.

**Закрепление:** новый rootfs bake с исходным обработчиком, runtime tree SHA1 `6f9822e7d72e8e4a4d4f0be4b1bcc66abd47b743`; пересобрать `image/rootfs.img` и SHA256SUMS, старый образ сохранить в archive. Остаточная аппаратная/ядровая проблема, если будет наблюдаться без user-space фильтра, требует отдельного измерения сырого GPIO/квадратуры; текущий kernel input event не раскрывает фазы A/B.

**Результат bake 14:57:** `image/rootfs.img` SHA256 `4e7a5de9d9ea2dc2ae8b15052812d7db15eaa1f10bb6032fa361f538621dafb3`, runtime tree SHA1 `6f9822e7d72e8e4a4d4f0be4b1bcc66abd47b743`. Четыре критичных файла выгружены из ext4 через debugfs и побайтно совпали с overlay. Старый rootfs `bdfd7b31…` сохранён в `image/archive-20261020-pre-filter-removal/`.

**Уточнение к причине задержки:** «до 550 мс» — только если после последнего заблокированного тика вращение остановить. При непрерывном развороте фильтр мог блокировать встречные тики неограниченно: каждый такой тик перезаписывал timestamp, а направление оставалось старым. Это напрямую объясняет, почему при вращении вниз после максимума команды могли не уходить вообще, пока пользователь не остановится.

**Сетевая проверка протокола:** Apple AMS spec определяет команды VolumeUp/VolumeDown как ID 5/6, Player Volume как строку 0.0–1.0, а регистрацию атрибутов — как механизм получения текущего и последующих изменённых значений. Спецификация отдельно предупреждает: успешная запись команды гарантирует доставку активному медиаплееру, но не гарантирует, что плеер её выполнил. В просмотренных актуальных источниках не найдено подтверждения конкретной регрессии AMS в iOS 27. Это не было причиной задержки, которую мы только что убрали. В текущей архитектуре Car Thing отправляет AMS-команды самому iPhone; отдельного управления AirPlay-устройством в Car Thing нет, маршрут воспроизведения выбирает iOS.

### 2026-10-20 — очередь команд громкости при развороте энкодера

Исправлен кодовый путь в `carthing_runtime.py`: вместо отдельной asyncio-задачи и ожидания в общем HCI lock на каждый тик iPhone volume-команды проходят через одного worker-а. Ещё не отправленные шаги противоположного знака сокращаются друг с другом; уже начатую BLE-запись отменить нельзя. В лог добавлены `volume queue input/dispatch/complete` с остатком очереди и временем выполнения, чтобы следующий физический тест показал, копилась ли задержка в команде или раньше по тракту. Три unit-теста очереди прошли; `py_compile` и `git diff --check` прошли.

Коммит `a29a8a8` отправлен в `origin/assistant-v2-whisper-streaming`. На Car Thing не выкатывалось: Tailscale API на момент проверки показывал UGREEN `online=false`, `lastSeen=2026-10-20T12:33:45Z`, SSH через NAS истёк по таймауту. Поэтому baked image и поведение устройства не изменились; не считать это аппаратно проверенным исправлением.

**Поправка 2026-10-20:** предыдущая проверка ошибочно остановилась на offline-статусе tailnet и не проверила LAN. Mac видит NAS `aknas` по `192.168.1.128`, NAS отвечает на LAN; route к `172.16.42.77` на Mac уходит в utun, поэтому прямой Car Thing SSH с Mac не является локальным путём. Tailscale SSH доступ на NAS не работает в текущем состоянии, а прямой LAN SSH `EXRECTOR@192.168.1.128` запросил пароль; проверенные SSH-ключи не приняли. На Car Thing через USB-линк в NAS этим заходом ещё не вошёл и деплой не выполнял. Пароли не извлекались и не записывались.
