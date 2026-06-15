"""state_paths — persistent-state mount contract (runtime-contract.md §Persistent State).

Единый владелец путей persistent-состояния. ОСНОВАТЕЛЬНО, а не заплаткой:
`/run` — временный; persistent-состояние живёт ТОЛЬКО на смонтированном
`/run/carthing-state` (vfat mmcblk0p1). Если mount отсутствует — рантайм обязан
войти в degraded-режим, а НЕ молча создавать временную базу пар/доверенных на tmpfs
(иначе бонды/доверенные теряются на ребуте и плодят «несколько устройств»).

Persistent владеет: keys.json · trusted-devices.json · settings.json · crash-маркеры.
"""

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)

STATE_ROOT = Path(os.environ.get("CARTHING_STATE_ROOT", "/run/carthing-state"))
# Подкаталог проекта внутри state-раздела (bumble namespace = "CarThing").
STATE_DIR = STATE_ROOT / "carthing"

KEYS_PATH = STATE_DIR / "keys.json"          # крипто-keystore Bumble (его формат, отдельный слой)
# [CLAUDE 2026-06-03] ЕДИНЫЙ файл состояния приложения: настройки + доверенные/карточки в ОДНОМ
# state.json = {"schema":2, "devices":[...], "settings":{...}}. Один источник правды (минимализм).
STATE_FILE = STATE_DIR / "state.json"
# Совместимость: старые отдельные файлы — только для одноразовой миграции в state.json.
LEGACY_TRUSTED_PATH = STATE_DIR / "trusted-devices.json"
LEGACY_SETTINGS_PATH = STATE_DIR / "settings.json"
# Алиасы (исторические имена) теперь указывают на единый файл.
TRUSTED_PATH = STATE_FILE
SETTINGS_PATH = STATE_FILE
CRASH_MARKER = STATE_DIR / "crash.marker"


def _is_mountpoint(path: Path) -> bool:
    try:
        return os.path.ismount(str(path))
    except Exception:
        return False


# [CLAUDE 2026-06-03] DEV-режим (Mac/run_local): на маке нет смонтированного state-раздела,
# поэтому ismount() = False и настройки/доверенные НЕ сохранялись между запусками. Флаг
# CARTHING_STATE_ALLOW_NONMOUNT=1 разрешает считать обычную (создаваемую) папку persistent —
# ТОЛЬКО для dev на Mac. На устройстве флаг не ставится -> поведение прежнее (нужен real mount).
_ALLOW_NONMOUNT = os.environ.get("CARTHING_STATE_ALLOW_NONMOUNT") == "1"


def persistent_available() -> bool:
    """True если /run/carthing-state — настоящий mountpoint (устройство), ИЛИ включён dev-режим
    CARTHING_STATE_ALLOW_NONMOUNT и каталог доступен для записи (Mac/run_local)."""
    if _is_mountpoint(STATE_ROOT):
        return True
    if _ALLOW_NONMOUNT:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False
    return False


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
    if not KEYS_PATH.exists():
        KEYS_PATH.write_text("{}")
    if not STATE_FILE.exists():
        write_state({})        # создаст state.json с миграцией из legacy при наличии


# ── ЕДИНЫЙ state.json: settings + devices в одном файле (один источник правды) ──────
def read_state() -> dict:
    """Прочитать единый state.json. Если его ещё нет — один раз импортировать из legacy
    trusted-devices.json + settings.json (ничего не теряем при переходе на единый файл)."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text() or "{}")
            return data if isinstance(data, dict) else {}
    except Exception as e:
        # [CLAUDE 2026-06-13] СУЩЕСТВУЮЩИЙ state.json не читается = повреждение
        # (а не первый старт). Раньше тихо уходили в дефолт -> «настройки/тема
        # просто пропали». Теперь ГРОМКО (ERROR) + пробуем последний бэкап рядом,
        # прежде чем отдать пустой стейт. На vfat (p1) повреждение state.json при
        # жёстком обрыве питания ВОЗМОЖНО; атомарная запись (temp+fsync+rename)
        # снижает риск, но не исключает — поэтому backup-recovery здесь актуален.
        _log.error("read_state: EXISTING state.json unreadable (corruption?): %s", e)
        try:
            import glob
            bks = sorted(glob.glob(str(STATE_FILE.parent / "backup-*" / "state.json")))
            if bks:
                data = json.loads(open(bks[-1]).read() or "{}")
                if isinstance(data, dict):
                    _log.error("read_state: recovered registry from backup %s", bks[-1])
                    # [CLAUDE 2026-06-15] самолечение: сразу переписать испорченный
                    # основной восстановленными данными, чтобы файл не висел битым.
                    try:
                        _atomic_write_text(
                            STATE_FILE,
                            json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
                        )
                        _log.error("read_state: healed primary state.json from backup")
                    except Exception as he:
                        _log.warning("read_state: heal write failed: %s", he)
                    return data
        except Exception as be:
            _log.error("read_state: backup recovery failed: %s", be)
    # миграция из старых отдельных файлов
    data: dict = {}
    try:
        if LEGACY_TRUSTED_PATH.exists():
            t = json.loads(LEGACY_TRUSTED_PATH.read_text() or "{}")
            if isinstance(t, dict) and "devices" in t:
                data["schema"] = t.get("schema", 2)
                data["devices"] = t["devices"]
            elif isinstance(t, list):
                data["schema"] = 2
                data["devices"] = t
    except Exception as e:
        _log.warning("legacy trusted migrate failed: %s", e)
    try:
        if LEGACY_SETTINGS_PATH.exists():
            s = json.loads(LEGACY_SETTINGS_PATH.read_text() or "{}")
            if isinstance(s, dict):
                data["settings"] = s
    except Exception as e:
        _log.warning("legacy settings migrate failed: %s", e)
    return data


def _atomic_write_text(path: Path, payload: str) -> None:
    """Атомарная запись: tmp + fsync + rename. На vfat окно порчи меньше, но не
    нулевое — поэтому держим валидный бэкап рядом (см. _rotate_state_backup)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    try:
        fd = os.open(str(tmp), os.O_RDONLY)
        os.fsync(fd); os.close(fd)
    except Exception:
        pass
    os.replace(str(tmp), str(path))


def _rotate_state_backup(payload: str, keep: int = 3) -> None:
    """[CLAUDE 2026-06-15] Создание бэкапов, без которых read_state-recovery был
    мёртв. Пишем валидный снимок state.json в backup-<ts>/ ДО основного файла:
    если обрыв питания испортит основной — read_state поднимет это из backup-*.
    Держим последние keep снимков."""
    import glob
    import shutil
    import time
    try:
        bdir = STATE_DIR / ("backup-%010d" % int(time.time()))
        bdir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(bdir / "state.json", payload)
        existing = sorted(glob.glob(str(STATE_DIR / "backup-*")))
        for old in existing[:-keep]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception as e:
        _log.warning("state backup rotate failed: %s", e)


def write_state(updates: dict) -> None:
    """Слить updates в state.json и атомарно записать (read-modify-write — секции не затирают
    друг друга). На устройстве — при живом mount; на Mac dev — через ALLOW_NONMOUNT."""
    try:
        require_persistent()
    except PersistentStateError as e:
        _log.warning("write_state degraded (not persistent): %s", e)
        return
    data = read_state()
    data.update(updates or {})
    payload = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    # Сначала валидный бэкап (страховка от порчи основного при обрыве записи),
    # затем основной файл. При порче основного read_state восстановится из backup-*.
    _rotate_state_backup(payload)
    _atomic_write_text(STATE_FILE, payload)
