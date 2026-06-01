# carthing-mcp — read-only MCP server (заготовка)

MCP-сервер, дающий агентам **безопасный read-only интерфейс к проекту Car Thing**. Сейчас
он читает ТОЛЬКО локальные файлы репозитория и `docs/`. Ни одной операции с устройством,
runtime, rootfs, Bluetooth, USB или flash здесь нет — намеренно.

## Зачем
Чтобы агент (Claude/Codex) мог быстро и безопасно узнать состояние проекта: что в git,
какие релиз-бандлы есть, из чего состоит userspace-рантайм, какие железо/boot/USB/BT
зафиксированы — **не подключаясь к устройству и ничего не меняя**.

## Жёсткие ограничения (соблюдены)
- НЕ меняет `overlay/usr/lib/carthing/*.py`, `rootfs.img`, `bootfs.bin`, `env.txt`.
- НЕ подключается к `172.16.42.77`, не делает SSH/flash/reboot.
- НЕ запускает `profilectl`/`bt-profile`/`usb-profile` (только статически читает их текст).
- НЕ тянет BlueZ/`bluetoothctl`/dbus и вообще никаких внешних зависимостей в read-логике.
- Все write/live-device инструменты **отсутствуют** (см. ниже). По умолчанию — только чтение.

## Структура
```
tools/carthing-mcp/
  core.py          # вся read-only логика: чистые функции, ТОЛЬКО stdlib. Реестр core.TOOLS.
  server.py        # тонкая FastMCP-обвязка (stdio), регистрирует те же инструменты.
  smoke_test.py    # прогон всех инструментов -> JSON. Без устройства и без пакета mcp.
  requirements.txt # mcp[cli] — нужен ТОЛЬКО для server.py.
  README.md
```
- **Корень репо** определяется автоматически (на 2 уровня выше файла) либо через
  `CARTHING_REPO_ROOT`.
- **Конверт ответа** у каждого инструмента: `{"ok": bool, "tool": str, "data": {...}}`
  или `{"ok": false, "tool": str, "error": str}`.
- **mock-режим** (`mock=True` / `--mock`): канонические данные без чтения репо — для проверки
  MCP-обвязки в окружении без проекта/устройства.

## Инструменты (все read-only)
| Инструмент | Что читает (источник) |
|---|---|
| `get_project_status` | корень репо, наличие ключевых путей, счётчики, git ветка/HEAD |
| `get_git_status` | `git status`/`git log` — ветка, чистота дерева, изменённые файлы, коммиты |
| `list_release_bundles` | каталоги `flash-bake-*`: `meta.json` (версия/описание), размеры rootfs/bootfs, SHA256SUMS |
| `read_runtime_manifest` | `overlay/usr/lib/carthing/*.py` — список + sha256 каждого, общий `tree_sha256`, entry из `overlay/etc/default/carthing` |
| `read_hardware_inventory_from_docs` | статический парс ключей возможностей из `hardware_inventory.py` (как текст) + скан упоминаний железа в `docs/*.md` |
| `list_runtime_files` | содержимое `overlay/usr/lib/carthing/` (py/native/vendor) с типом и размером |
| `summarize_boot_layout` | `meta.json` + `env.txt` бандла: шаги прошивки (адреса bootfs/rootfs), геометрия дисплея, env |
| `summarize_usb_profiles_from_repo` | текст `usb-profile`/`profilectl`: команды, список USB-профилей, домены (скрипты НЕ запускаются) |
| `summarize_bluetooth_architecture_from_repo` | докстринги BT-модулей рантайма + ссылки на BT-доки (устройство не опрашивается) |

## Запуск
```bash
# Smoke-test (без mcp, без устройства):
python3 tools/carthing-mcp/smoke_test.py            # читает реальный репо
python3 tools/carthing-mcp/smoke_test.py --mock     # канонические данные
python3 tools/carthing-mcp/smoke_test.py --tool get_git_status

# Как MCP-сервер (stdio):
pip install "mcp[cli]"
python3 tools/carthing-mcp/server.py
```
Интеграция в конфиг Codex/Claude НЕ делается автоматически — только код и документация.

## Что НАМЕРЕННО не реализовано (write / live-device)
В read-only заготовке этих инструментов нет вообще (перечислены в `core.DISABLED_BY_DESIGN`
исключительно для прозрачности будущего слоя):
`deploy_runtime_files`, `restart_runtime`, `flash_device`, `reboot_device`, `set_usb_profile`,
`run_profilectl`, `ssh_exec`, `send_media_command`, `read_live_runtime_state`.

Причина: любые изменения и любой доступ к живому устройству — отдельный, согласованный слой.
Когда дойдём до управления, точкой входа для смены режима должен быть **runtime-intent
`select_mode(...)`**, а не прямой вызов `profilectl`/shell (см. модель состояния проекта:
view ≠ mode ≠ route ≠ pairing; GUI/инструменты не дёргают shell напрямую).

## Следующий этап (когда разрешат)
1. Канал к устройству: по USB — через NCM/SSH (быстрая труба), по BT — кастомный GATT
   companion-сервис (контракт описать здесь, реализацию на устройстве согласовать с Codex).
2. `read_live_runtime_state` — парс `/run/carthing/runtime-bt.json` (now-playing, supported-команды,
   уведомления, подключение) в read-only.
3. Только потом — write-слой (`select_mode`, рестарт, профили) с явными гейтами и подтверждением.
