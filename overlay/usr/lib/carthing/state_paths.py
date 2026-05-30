"""state_paths — persistent-state mount contract (runtime-contract.md §Persistent State).

Единый владелец путей persistent-состояния. ОСНОВАТЕЛЬНО, а не заплаткой:
`/run` — временный; persistent-состояние живёт ТОЛЬКО на смонтированном
`/run/carthing-state` (vfat mmcblk0p1). Если mount отсутствует — рантайм обязан
войти в degraded-режим, а НЕ молча создавать временную базу пар/доверенных на tmpfs
(иначе бонды/доверенные теряются на ребуте и плодят «несколько устройств»).

Persistent владеет: keys.json · trusted-devices.json · settings.json · crash-маркеры.
"""

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("CARTHING_STATE_ROOT", "/run/carthing-state"))
# Подкаталог проекта внутри state-раздела (bumble namespace = "CarThing").
STATE_DIR = STATE_ROOT / "carthing"

KEYS_PATH = STATE_DIR / "keys.json"
TRUSTED_PATH = STATE_DIR / "trusted-devices.json"
SETTINGS_PATH = STATE_DIR / "settings.json"
CRASH_MARKER = STATE_DIR / "crash.marker"


def _is_mountpoint(path: Path) -> bool:
    try:
        return os.path.ismount(str(path))
    except Exception:
        return False


def persistent_available() -> bool:
    """True только если /run/carthing-state — НАСТОЯЩИЙ mountpoint (не tmpfs-папка)."""
    return _is_mountpoint(STATE_ROOT)


class PersistentStateError(RuntimeError):
    """Persistent-раздел не смонтирован — рантайм должен уйти в degraded, не выдумывать базу."""


def require_persistent() -> Path:
    """Гарантирует доступность persistent-состояния. Поднимает ошибку, если mount нет.

    Возвращает STATE_DIR (создаёт его ВНУТРИ смонтированного раздела, что безопасно).
    """
    if not persistent_available():
        raise PersistentStateError(
            f"{STATE_ROOT} is not a mountpoint — refusing to create transient "
            f"pairing/trusted state on tmpfs (degraded mode)."
        )
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def ensure_files() -> None:
    """Создаёт пустые persistent-файлы (как S11-runtime-state), только при живом mount."""
    require_persistent()
    for path, default in (
        (KEYS_PATH, "{}"),
        (TRUSTED_PATH, "[]"),
        (SETTINGS_PATH, "{}"),
    ):
        if not path.exists():
            path.write_text(default)
