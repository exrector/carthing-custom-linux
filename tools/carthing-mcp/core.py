"""carthing-mcp · core (read-only).

Чистые функции-инструменты MCP-сервера для проекта Car Thing. Каждая ТОЛЬКО читает
локальные файлы репозитория и docs. НИКАКИХ сетевых/устройственных операций, никакого
SSH/flash/profilectl/Bluetooth/USB, никаких записей. Зависимостей кроме stdlib нет.

Контракт ответа: каждая функция возвращает JSON-сериализуемый dict-конверт:
    {"ok": bool, "tool": str, "data": {...}}            при успехе
    {"ok": false, "tool": str, "error": str}            при ошибке

`mock=True` -> вернуть представительные канонические данные без чтения репо (для теста
MCP-обвязки без проекта/устройства).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

# ─── разрешение корня репозитория ─────────────────────────────────────────────
# Файл лежит в <repo>/tools/carthing-mcp/core.py -> корень на два уровня выше.
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def repo_root(root: str | os.PathLike | None = None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    env = os.environ.get("CARTHING_REPO_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_ROOT


RUNTIME_DIR = Path("overlay/usr/lib/carthing")
LIBEXEC_DIR = Path("overlay/usr/libexec/carthing")
DOCS_DIR = Path("docs")
DEFAULTS_FILE = Path("overlay/etc/default/carthing")

# ─── мелкие read-only помощники ───────────────────────────────────────────────
def _ok(tool: str, data: dict) -> dict:
    return {"ok": True, "tool": tool, "data": data}


def _err(tool: str, msg: str) -> dict:
    return {"ok": False, "tool": tool, "error": msg}


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _module_docstring(path: Path) -> str:
    """Первый тройной-кавычный докстринг файла (без выполнения кода)."""
    text = _read_text(path, 8000)
    m = re.search(r'^\s*(?:[rRbBuU]{0,2})("""|\'\'\')(.*?)\1', text, re.DOTALL)
    if not m:
        return ""
    doc = m.group(2).strip()
    return doc.split("\n\n")[0].strip()  # только первый абзац


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def _runtime_py(root: Path) -> list[Path]:
    d = root / RUNTIME_DIR
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.py") if p.name != "__init__.py")


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


# ═══════════════════════════ ИНСТРУМЕНТЫ (read-only) ══════════════════════════
def get_project_status(root=None, mock: bool = False) -> dict:
    tool = "get_project_status"
    if mock:
        return _ok(tool, {"repo_root": "/mock/carthing", "exists": True,
                          "runtime_py_files": 31, "docs": 24, "scripts": 28,
                          "release_bundles": 4, "branch": "release-integration",
                          "head": "deadbeef mock commit"})
    r = repo_root(root)
    if not r.is_dir():
        return _err(tool, f"repo root not found: {r}")
    head = _git(r, "log", "-1", "--oneline")
    branch = _git(r, "rev-parse", "--abbrev-ref", "HEAD")
    bundles = [p.name for p in r.iterdir() if p.is_dir() and p.name.startswith("flash-bake")]
    data = {
        "repo_root": str(r),
        "exists": True,
        "key_paths": {
            "runtime_dir": (r / RUNTIME_DIR).is_dir(),
            "libexec_dir": (r / LIBEXEC_DIR).is_dir(),
            "docs_dir": (r / DOCS_DIR).is_dir(),
            "native_rotator": (r / RUNTIME_DIR / "libcarthing_frame.so").exists(),
        },
        "runtime_py_files": len(_runtime_py(r)),
        "docs": len(list((r / DOCS_DIR).glob("*.md"))) if (r / DOCS_DIR).is_dir() else 0,
        "scripts": len(list((r / "scripts").glob("*"))) if (r / "scripts").is_dir() else 0,
        "release_bundles": len(bundles),
        "branch": (branch or "").strip() or None,
        "head": (head or "").strip() or None,
    }
    return _ok(tool, data)


def get_git_status(root=None, mock: bool = False) -> dict:
    tool = "get_git_status"
    if mock:
        return _ok(tool, {"branch": "release-integration", "clean": False,
                          "changed": ["tools/carthing-mcp/core.py"],
                          "recent_commits": ["deadbeef mock: add mcp"]})
    r = repo_root(root)
    porcelain = _git(r, "status", "--porcelain")
    if porcelain is None:
        return _err(tool, "git unavailable or not a repository")
    branch = (_git(r, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    changed = [ln[3:] for ln in porcelain.splitlines() if ln.strip()]
    log = _git(r, "log", "-8", "--oneline") or ""
    return _ok(tool, {
        "branch": branch or None,
        "clean": len(changed) == 0,
        "changed_count": len(changed),
        "changed": changed[:50],
        "recent_commits": [ln for ln in log.splitlines() if ln.strip()],
    })


def list_release_bundles(root=None, mock: bool = False) -> dict:
    tool = "list_release_bundles"
    if mock:
        return _ok(tool, {"count": 1, "bundles": [{
            "name": "flash-bake-unified-stable-mock",
            "version": "mock-2026", "has_sha256sums": True,
            "rootfs_img_bytes": 536870912, "bootfs_bin_bytes": 180355072}]})
    r = repo_root(root)
    bundles = []
    for d in sorted(r.iterdir() if r.is_dir() else []):
        if not (d.is_dir() and d.name.startswith("flash-bake")):
            continue
        meta = {}
        mp = d / "meta.json"
        if mp.exists():
            try:
                meta = json.loads(_read_text(mp))
            except Exception:
                meta = {}
        bundles.append({
            "name": d.name,
            "version": meta.get("version"),
            "description": meta.get("description"),
            "has_meta": mp.exists(),
            "has_sha256sums": (d / "SHA256SUMS").exists(),
            "has_env_txt": (d / "env.txt").exists(),
            "rootfs_img_bytes": _size(d / "rootfs.img") or None,
            "bootfs_bin_bytes": _size(d / "bootfs.bin") or None,
        })
    return _ok(tool, {"count": len(bundles), "bundles": bundles})


def read_runtime_manifest(root=None, mock: bool = False) -> dict:
    tool = "read_runtime_manifest"
    if mock:
        return _ok(tool, {"entry": "/usr/lib/carthing/carthing_runtime.py",
                          "py_count": 31, "tree_sha256": "mockmockmock",
                          "files": [{"name": "carthing_runtime.py", "bytes": 1234,
                                     "sha256": "abc"}]})
    r = repo_root(root)
    files = _runtime_py(r)
    if not files:
        return _err(tool, f"no runtime .py under {r / RUNTIME_DIR}")
    entries, tree_lines = [], []
    for p in files:
        sha = _sha256_file(p)
        entries.append({"name": p.name, "bytes": _size(p), "sha256": sha})
        tree_lines.append(f"{sha}  {p.name}")
    tree_sha = hashlib.sha256(("\n".join(tree_lines) + "\n").encode()).hexdigest()
    # entry point из overlay/etc/default/carthing (CARTHING_RUNTIME_ENTRY=...)
    entry = None
    dtxt = _read_text(r / DEFAULTS_FILE, 8000)
    m = re.search(r"CARTHING_RUNTIME_ENTRY=([^\s#]+)", dtxt)
    if m:
        entry = m.group(1).strip().strip('"').strip("'")
    return _ok(tool, {
        "entry": entry,
        "py_count": len(entries),
        "tree_sha256": tree_sha,
        "files": entries,
    })


def read_hardware_inventory_from_docs(root=None, mock: bool = False) -> dict:
    tool = "read_hardware_inventory_from_docs"
    if mock:
        return _ok(tool, {"runtime_capability_keys": ["display_drm", "audio_playback_t9015"],
                          "doc_mentions": {"display": ["docs/mock.md"]}})
    r = repo_root(root)
    # 1) ключи возможностей, ОБЪЯВЛЕННЫЕ в источнике рантайма (статический парс текста, без запуска)
    cap_keys: list[str] = []
    inv = r / RUNTIME_DIR / "hardware_inventory.py"
    if inv.exists():
        txt = _read_text(inv)
        cap_keys = sorted(set(re.findall(r'["\']([a-z][a-z0-9_]{2,})["\']\s*:', txt)))
    # 2) упоминания железа в docs (что и где задокументировано)
    keywords = ["display_drm", "drm", "backlight", "touch", "encoder", "tmd2772",
                "t9015", "pdm", "thermal", "mfi", "accelerometer", "lis2dh", "efuse",
                "usid", "zram", "hwrng", "sar adc", "als", "proximity"]
    mentions: dict[str, list[str]] = {}
    docs_dir = r / DOCS_DIR
    if docs_dir.is_dir():
        for doc in sorted(docs_dir.glob("*.md")):
            low = _read_text(doc).lower()
            for kw in keywords:
                if kw in low:
                    mentions.setdefault(kw, []).append(str(doc.relative_to(r)))
    return _ok(tool, {
        "source_note": "capability keys = static text-parse of hardware_inventory.py; "
                       "doc_mentions = keyword scan of docs/*.md (no device, no execution)",
        "runtime_capability_keys": cap_keys,
        "doc_mentions": mentions,
    })


def list_runtime_files(root=None, mock: bool = False) -> dict:
    tool = "list_runtime_files"
    if mock:
        return _ok(tool, {"count": 2, "files": [
            {"name": "carthing_runtime.py", "kind": "py", "bytes": 1234},
            {"name": "libcarthing_frame.so", "kind": "native", "bytes": 5678}]})
    r = repo_root(root)
    d = r / RUNTIME_DIR
    if not d.is_dir():
        return _err(tool, f"runtime dir not found: {d}")
    out = []
    for p in sorted(d.iterdir()):
        if p.name == "__pycache__":
            continue
        if p.is_dir():
            kind = "dir"
            n = sum(1 for _ in p.rglob("*") if _.is_file())
            out.append({"name": p.name + "/", "kind": kind, "files": n})
            continue
        kind = ("py" if p.suffix == ".py"
                else "native" if p.suffix == ".so"
                else p.suffix.lstrip(".") or "other")
        out.append({"name": p.name, "kind": kind, "bytes": _size(p)})
    return _ok(tool, {"count": len(out), "files": out})


def summarize_boot_layout(root=None, mock: bool = False) -> dict:
    tool = "summarize_boot_layout"
    if mock:
        return _ok(tool, {"display": {"width": 480, "height": 800},
                          "flash_steps": [{"file": "bootfs.bin", "address": 0}],
                          "source_bundle": "flash-bake-mock"})
    r = repo_root(root)
    # берём представительный бандл (последний по имени) — читаем meta.json + env.txt
    bundle = None
    for d in sorted((p for p in r.iterdir() if p.is_dir() and p.name.startswith("flash-bake")),
                    reverse=True) if r.is_dir() else []:
        if (d / "meta.json").exists() or (d / "env.txt").exists():
            bundle = d
            break
    if bundle is None:
        return _err(tool, "no flash-bake bundle with meta.json/env.txt found")
    meta = {}
    try:
        meta = json.loads(_read_text(bundle / "meta.json"))
    except Exception:
        pass
    flash_steps = []
    for step in meta.get("steps", []):
        v = step.get("value")
        if isinstance(v, dict) and isinstance(v.get("data"), dict):
            flash_steps.append({"type": step.get("type"),
                                "file": v["data"].get("filePath"),
                                "address": v.get("address")})
        elif step.get("type") == "bulkcmd":
            flash_steps.append({"type": "bulkcmd", "cmd": v})
    env = {}
    for ln in _read_text(bundle / "env.txt").splitlines():
        if "=" in ln:
            k, val = ln.split("=", 1)
            env[k.strip()] = val.strip()
    disp = {"width": _to_int(env.get("display_width")),
            "height": _to_int(env.get("display_height")),
            "stack": env.get("display_stack")}
    return _ok(tool, {
        "source_bundle": bundle.name,
        "bundle_version": meta.get("version"),
        "display": disp,
        "boot_part": env.get("boot_part"),
        "bootcmd": env.get("bootcmd"),
        "flash_steps": flash_steps,
        "note": "статичное чтение meta.json/env.txt бандла; устройство не опрашивается",
    })


def _to_int(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def summarize_usb_profiles_from_repo(root=None, mock: bool = False) -> dict:
    tool = "summarize_usb_profiles_from_repo"
    if mock:
        return _ok(tool, {"commands": ["get", "set", "apply", "list"],
                          "profiles": ["ncm", "ncm,audio"]})
    r = repo_root(root)
    usb = r / LIBEXEC_DIR / "usb-profile"
    if not usb.exists():
        return _err(tool, f"usb-profile not found: {usb}")
    txt = _read_text(usb)
    # команды usage-строки: "usage: usb-profile get|set <profile>|apply|list"
    commands = []
    mu = re.search(r"usage:\s*usb-profile\s+([^\n]+)", txt)
    if mu:
        commands = re.findall(r"[a-z]+", mu.group(1))
        commands = [c for c in dict.fromkeys(commands) if c not in ("profile", "usb")]
    # список профилей из heredoc после 'list)'
    profiles = []
    mh = re.search(r"list\)\s*cat\s*<<'EOF'\n(.*?)\nEOF", txt, re.DOTALL)
    if mh:
        profiles = [ln.strip() for ln in mh.group(1).splitlines() if ln.strip()]
    # доменный диспетчер
    pctl = r / LIBEXEC_DIR / "profilectl"
    domains = []
    if pctl.exists():
        md = re.search(r"domains:\s*([^\n]+)", _read_text(pctl))
        if md:
            # строка вида: echo "domains: usb bt audio sensor debug" >&2  -> только слова
            domains = re.findall(r"[a-z]+", md.group(1))
    return _ok(tool, {
        "commands": commands,
        "profiles": profiles,
        "profilectl_domains": domains,
        "note": "статичный разбор текста usb-profile/profilectl; СКРИПТЫ НЕ ЗАПУСКАЮТСЯ, "
                "переключение профилей сделано НЕдоступным намеренно (read-only)",
    })


def summarize_bluetooth_architecture_from_repo(root=None, mock: bool = False) -> dict:
    tool = "summarize_bluetooth_architecture_from_repo"
    if mock:
        return _ok(tool, {"stack": "Bumble (no BlueZ)",
                          "components": {"accessory_orchestrator.py": "BT owner"}})
    r = repo_root(root)
    rd = r / RUNTIME_DIR
    # роли ключевых BT-модулей = их первый докстринг (читаем текст, не выполняем)
    comp = {}
    for name in ["accessory_orchestrator.py", "ams_client.py", "ancs_client.py",
                 "cts_client.py", "a2dp_bridge.py", "keyboard_hid.py", "iphone_service.py",
                 "ble_transport.py", "carthing_link.py"]:
        p = rd / name
        if p.exists():
            comp[name] = _module_docstring(p) or "(no docstring)"
    # упоминания BT-стека в docs
    bt_docs = []
    docs_dir = r / DOCS_DIR
    if docs_dir.is_dir():
        for doc in sorted(docs_dir.glob("*.md")):
            low = _read_text(doc).lower()
            if any(k in low for k in ("bumble", "ams", "ancs", "a2dp", "gatt", "ble ", "bluetooth")):
                bt_docs.append(str(doc.relative_to(r)))
    return _ok(tool, {
        "stack": "Bumble on raw HCI — BlueZ/bluetoothctl/dbus НЕ используются (запрещено в проекте)",
        "components": comp,
        "doc_references": bt_docs,
        "note": "докстринги модулей + скан docs; устройство не опрашивается",
    })


# ─── реестр инструментов (для server.py и smoke_test.py) ──────────────────────
TOOLS = {
    "get_project_status": get_project_status,
    "get_git_status": get_git_status,
    "list_release_bundles": list_release_bundles,
    "read_runtime_manifest": read_runtime_manifest,
    "read_hardware_inventory_from_docs": read_hardware_inventory_from_docs,
    "list_runtime_files": list_runtime_files,
    "summarize_boot_layout": summarize_boot_layout,
    "summarize_usb_profiles_from_repo": summarize_usb_profiles_from_repo,
    "summarize_bluetooth_architecture_from_repo": summarize_bluetooth_architecture_from_repo,
}

# Намеренно НЕ реализовано (write / live-device). Перечислено для прозрачности;
# в read-only заготовке этих инструментов НЕТ. Появятся отдельным согласованным слоем.
DISABLED_BY_DESIGN = [
    "deploy_runtime_files", "restart_runtime", "flash_device", "reboot_device",
    "set_usb_profile", "run_profilectl", "ssh_exec", "send_media_command",
    "read_live_runtime_state",  # требует SSH/NCM к 172.16.42.77 — намеренно выключено
]
