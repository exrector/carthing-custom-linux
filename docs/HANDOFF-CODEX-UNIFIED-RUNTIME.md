# HANDOFF для Codex — запечь unified runtime в правильный rootfs. 2026-05-31

Контекст: правильная перепрошивка №2 (efuse QN19) — твой курированный **kernel (нужный набор
драйверов)** + **rootfs**. Сюда нужно влить наш готовый и обкатанный **userspace** (unified runtime).

## ЧТО ЗАПЕЧЬ (источник истины)
- Репо/ветка: `carthing-release-integration` , ветка **`release-integration`**, коммит `010f1c4`+.
- Userspace = **все `overlay/usr/lib/carthing/*.py`** (31 файл). sha-дерева для сверки после bake:
  `a4dd271e7335734285ae9a27fd5993c0485d76c5`
  (в каталоге: `ls *.py | sort | xargs shasum | shasum`).
- Entry: в `/etc/default/carthing` → **`CARTHING_RUNTIME_ENTRY=/usr/lib/carthing/carthing_runtime.py`**.
- `vendor/bumble` — наш тree использует bumble из rootfs; оставить рабочий (тот же baseline).
- Boot-цепочка без изменений: `init-wrapper → S50-carthing-remote → run-media-remote → exec $ENTRY`.
- Support tools тоже источник истины в этом репо: `overlay/usr/libexec/carthing/profilectl` +
  `usb-profile`/`bt-profile`/`audio-profile`/`sensor-profile`/`debug-profile`.

## Рецепт bake (как я делал на лету, без полной пересборки)
В **копию** твоего rootfs.img (не мутируя общий build-том):
```
e2cp -G 0 -O 0 <each *.py>  rootfs.img:/usr/lib/carthing/
# + выставить CARTHING_RUNTIME_ENTRY=…/carthing_runtime.py в /etc/default/carthing внутри образа
```
Либо просто положить наши *.py в overlay перед сборкой rootfs.

## Архитектура (14-сервисный split — что есть)
carthing_runtime(entry) · state_paths · identity_service · **accessory_orchestrator** (CTKD-config +
фазовая машина + видимость) · runtime_model (одна MediaSession) · iphone_service(AMS+ANCS+CTS) ·
gui_controller (ОДИН home-surface + views) · transfer_service+transfer_control (A2DP relay+backchannel) ·
settings_service · hardware_inventory · mac_service(каркас Ф4). Перенесено из services-experiment:
ancs/cts/keyboard_hid/carthing_link. Сохранён GUI-субстрат (screens/ui_*/app_state/intents) + a2dp_bridge.

**Сознательные консолидации (НЕ ищи отдельные файлы):** advertising — ВНУТРИ accessory_orchestrator;
hid-репорты — в keyboard_hid (отдельных advertising_service/hid_profile нет, это минимализм, не пропуск).

## ✅ Валидировано на железе (REMOTE = ядро)
Один home-surface (без свайпа столов; Settings — кнопкой, уведомления — свайпом вниз) · одно имя
efuse · iPhone цепляется ТОЛЬКО пультом (не колонкой) · **sticky-реконнект непрерывный bonded-only
(прилипает после ЛЮБОГО отсутствия)** · AMS-метадата + живой прогресс (развязан с громкостью) ·
artist переносится в границах · TZ локальный (MSK) · **ANCS-уведомления**: список (имя приложения+текст,
без «iPhone»/заголовков), пульс-индикатор под энкодером, свайп-влево = очистить двусторонне ·
энкодер=громкость · CTKD-pairing config заложен.

## ⏳ Не блокирует REMOTE, доделать после
- **CTKD classic link_key**: bumble PairingConfig без CTKD-ручки (sc/mitm/bonding/delegate) — нужен
  разбор SMP-key-distribution. Сейчас пара даёт ltk/irk. Transfer без CTKD имеет путь (classic-пара
  при первом мосте через safe_link_key_provider).
- Transfer/Routes live (нужен Fosi) · Mac-источник(Ф4) · голосовой ассистент(Ф5, место в баре заложено) ·
  proximity-дисплей · USB-C audio · default_mode · Settings→Источники/Динамики+System (в очереди).

## ⚠️ ВАЖНО про kernel
configfs-usb-switch / capability-profile-safe сборки у меня **reboot-loop'или** на №2 (configfs-NCM
не поднимался для macOS / boot не валидирован). Я откатился на заведомо-рабочий образ
(`flash-device1-attach`, встроенный g_ncm). Для финала — kernel, который **проверен на загрузку +
NCM-на-macOS**; userspace (наш) от kernel не зависит (feature-gate через hardware_inventory).
</content>
