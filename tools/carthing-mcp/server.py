"""carthing-mcp · MCP server (stdio).

Тонкая обвязка над core.py: регистрирует ТОЛЬКО read-only инструменты в FastMCP.
Никаких write/live-device инструментов здесь нет (см. core.DISABLED_BY_DESIGN и README).

Запуск (stdio, для Claude Code / любого MCP-клиента):
    pip install "mcp[cli]"
    python server.py
"""

from __future__ import annotations

import core

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover - зависит от окружения
    raise SystemExit(
        "Не найден пакет 'mcp'. Установи: pip install \"mcp[cli]\".\n"
        "Для проверки без MCP используй smoke_test.py (он работает на одном stdlib).\n"
        f"Импорт упал: {exc}"
    )

mcp = FastMCP("carthing-mcp")

_READONLY_HINTS = {"readOnlyHint": True, "destructiveHint": False,
                   "idempotentHint": True, "openWorldHint": False}


@mcp.tool(annotations=_READONLY_HINTS)
def get_project_status(mock: bool = False) -> dict:
    """Обзор репозитория Car Thing: пути, счётчики, git-ветка/HEAD. Только локальные файлы."""
    return core.get_project_status(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def get_git_status(mock: bool = False) -> dict:
    """git-статус проекта: ветка, чистота дерева, изменённые файлы, последние коммиты."""
    return core.get_git_status(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def list_release_bundles(mock: bool = False) -> dict:
    """Список релиз-бандлов (flash-bake-*): версия, описание, размеры rootfs/bootfs, наличие SHA256SUMS."""
    return core.list_release_bundles(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def read_runtime_manifest(mock: bool = False) -> dict:
    """Манифест userspace-рантайма: список *.py с sha256, общий tree_sha256, entry point."""
    return core.read_runtime_manifest(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def read_hardware_inventory_from_docs(mock: bool = False) -> dict:
    """Возможности железа: статические capability-ключи из источника + упоминания в docs/*.md."""
    return core.read_hardware_inventory_from_docs(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def list_runtime_files(mock: bool = False) -> dict:
    """Файлы каталога рантайма overlay/usr/lib/carthing (py/native/vendor) с типом и размером."""
    return core.list_runtime_files(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def summarize_boot_layout(mock: bool = False) -> dict:
    """Раскладка загрузки из бандла: шаги прошивки (адреса bootfs/rootfs), геометрия дисплея, env."""
    return core.summarize_boot_layout(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def summarize_usb_profiles_from_repo(mock: bool = False) -> dict:
    """USB-профили и команды из usb-profile/profilectl (статический разбор текста; скрипты НЕ запускаются)."""
    return core.summarize_usb_profiles_from_repo(mock=mock)


@mcp.tool(annotations=_READONLY_HINTS)
def summarize_bluetooth_architecture_from_repo(mock: bool = False) -> dict:
    """Архитектура BT (Bumble, без BlueZ): роли модулей (докстринги) + ссылки на docs."""
    return core.summarize_bluetooth_architecture_from_repo(mock=mock)


if __name__ == "__main__":
    mcp.run()
