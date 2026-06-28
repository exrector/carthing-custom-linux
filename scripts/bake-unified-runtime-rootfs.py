#!/usr/bin/env python3
"""Bake the validated unified runtime into a known-good Car Thing rootfs image.

This intentionally does not build a kernel. It takes a reviewed flash bundle
that already contains the hardware baseline, copies it to a new bundle, then
overlays the unified userspace files from this repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "overlay"
DEFAULT_BASE_BUNDLE = Path(
    "~/Documents/ПРОЕКТЫ/carthing-device-backups/artifacts/"
    "kernel-build-gcc6-nixos-20260524/flash-stock-plus-rescue-profile-20260525"
)
DEFAULT_ARTIFACT_PREFIX = "flash-bake-unified-stable"
EXPECTED_RUNTIME_TREE_SHA1 = "a4503dbd8e2b19dc9ebc4f9a4b327ae5f8987019"
NATIVE_RUNTIME_FILES = (
    "libcarthing_frame.so",
    "libcarthing_voice_dsp.so",
    "libopus.so.0",
    "libspeexdsp.so.1",
)
RETIRED_RUNTIME_FILES = (
    "a2dp_bridge.py",
    "aac_to_sbc_transcoder.py",
    "audio_local_sink.py",
    "audio_out_t9015.py",
    "carthing_link.py",
    "classic_profile_probe.py",
    "enrollment_manager.py",
    "ge2d.py",
    "ge2d_test.py",
    "helix_aac_decoder.py",
    "hid_pair.py",
    "iap2_service.py",
    "keyboard_hid.py",
    "libhelixaac.so",
    "libsbc.so",
    "link_manager.py",
    "local_sink_client.py",
    "mac_service.py",
    "media_remote.py",
    "media_remote_v3.py",
    "now_playing_ui.py",
    "operation_mode.py",
    "resource_policy.py",
    "route_graph.py",
    "route_planner.py",
    "sbc_decoder.py",
    "sbc_encoder.py",
    "sbc_synth.so",
    "session_runner.py",
    "system_menu.py",
    "transfer_control.py",
    "transfer_service.py",
    "trusted_device_registry.py",
    "trusted_devices.py",
    "virtual_connectors.py",
    "virtual_socket.py",
)
RETIRED_INIT_FILES = (
    ":S50-carthing-remote.disabled",
    "S50-carthing-remote",
    "S50-carthing-remote.disabled",
    # S60 — ошибочный дублёр автостарта (2026-06-10): настоящий стартер =
    # init-wrapper -> disabled-S50-carthing-remote. Вычищать из образов.
    "S60-carthing-runtime",
)


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_tree_sha1(runtime_dir: Path) -> str:
    lines: list[str] = []
    for path in sorted(runtime_dir.glob("*.py")):
        if path.name in RETIRED_RUNTIME_FILES:
            continue
        h = hashlib.sha1(path.read_bytes()).hexdigest()
        lines.append(f"{h}  {path.name}\n")
    return hashlib.sha1("".join(lines).encode()).hexdigest()


def e2mkdir_p(image: Path, directory: str) -> None:
    current = ""
    for part in [p for p in directory.strip("/").split("/") if p]:
        current += "/" + part
        proc = subprocess.run(
            ["e2mkdir", "-O", "0", "-G", "0", f"{image}:{current}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0 and "already exists" not in proc.stderr and "File exists" not in proc.stderr:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)


def e2copy_file(image: Path, src: Path, dest: str, *, mode: str = "0644") -> None:
    e2mkdir_p(image, str(Path(dest).parent))
    run(["e2cp", "-O", "0", "-G", "0", "-P", mode, str(src), f"{image}:{dest}"])


def e2read_file(image: Path, src: str, dest: Path) -> None:
    run(["e2cp", f"{image}:{src}", str(dest)])


def e2rm_file(image: Path, dest: str) -> None:
    proc = subprocess.run(
        ["e2rm", f"{image}:{dest}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 and "No such file" not in proc.stderr and "not found" not in proc.stderr:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)


def e2rm_tree(image: Path, dest: str) -> None:
    proc = subprocess.run(
        ["e2rm", "-r", f"{image}:{dest}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 and "No such file" not in proc.stderr and "not found" not in proc.stderr:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)


def e2path_exists(image: Path, dest: str) -> bool:
    proc = subprocess.run(
        ["e2ls", f"{image}:{dest}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode == 0


def copy_overlay_tree(image: Path, source: Path, dest_root: str) -> None:
    for src in sorted(source.rglob("*")):
        if not src.is_file():
            continue
        if src.name == ".DS_Store" or src.name.startswith("._") or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(source).as_posix()
        mode = f"{src.stat().st_mode & 0o777:04o}"
        e2copy_file(image, src, f"{dest_root.rstrip('/')}/{rel}", mode=mode)


def clean_retired_runtime(image: Path) -> None:
    for name in RETIRED_RUNTIME_FILES:
        e2rm_file(image, f"/usr/lib/carthing/{name}")


def patch_default_carthing(image: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="carthing-default-") as tmp_s:
        tmp = Path(tmp_s)
        default_path = tmp / "carthing"
        e2read_file(image, "/etc/default/carthing", default_path)
        text = default_path.read_text()

        replacements = {
            "CARTHING_BT_ALIAS=": "CARTHING_BT_ALIAS=",
            "CARTHING_RUNTIME_ENTRY=": "CARTHING_RUNTIME_ENTRY=/usr/lib/carthing/carthing_runtime.py",
            "CARTHING_A2DP_RECEIVER=": "CARTHING_A2DP_RECEIVER=",
            "CARTHING_A2DP_NAME=": "CARTHING_A2DP_NAME=",
            "CARTHING_A2DP_AUTOCONNECT=": "CARTHING_A2DP_AUTOCONNECT=0",
            # Карантин снят решением владельца 2026-06-10 (автостарт =
            # S60-carthing-runtime; рубильник: no-autostart на state-разделе).
            "CARTHING_BUMBLE_QUARANTINE=": "CARTHING_BUMBLE_QUARANTINE=0",
            "CARTHING_ALLOW_BUMBLE_RUN=": "CARTHING_ALLOW_BUMBLE_RUN=1",
            # Единый источник правды доверенных = state.json (унификация
            # 2026-06-03). Старое значение (trusted-devices.json) раздваивало
            # хранилище: под продуктовым стартером runtime затирал state.json
            # без колонок — Fosi «исчезал» после каждого boot (найдено 2026-06-10).
            "CARTHING_TRUSTED_DEVICES=": "CARTHING_TRUSTED_DEVICES=/run/carthing-state/carthing/state.json",
        }

        out: list[str] = []
        seen = set()
        for line in text.splitlines():
            replaced = False
            for prefix, new_line in replacements.items():
                if line.startswith(prefix):
                    out.append(new_line)
                    seen.add(prefix)
                    replaced = True
                    break
            if not replaced:
                out.append(line)

        for prefix, new_line in replacements.items():
            if prefix not in seen:
                out.append(new_line)
        if not any(line.startswith("CARTHING_EFUSE_USID=") for line in out):
            out.insert(out.index("CARTHING_BT_ALIAS=") + 1, "CARTHING_EFUSE_USID=/sys/class/efuse/usid")
        if not any(line.startswith("CARTHING_DEVICE_NAME_FALLBACK=") for line in out):
            out.insert(out.index("CARTHING_EFUSE_USID=/sys/class/efuse/usid") + 1, 'CARTHING_DEVICE_NAME_FALLBACK="Car Thing"')

        default_path.write_text("\n".join(out) + "\n")
        e2copy_file(image, default_path, "/etc/default/carthing", mode="0644")


def copy_runtime(image: Path) -> None:
    runtime_dir = OVERLAY / "usr/lib/carthing"
    actual = runtime_tree_sha1(runtime_dir)
    if actual != EXPECTED_RUNTIME_TREE_SHA1:
        raise SystemExit(
            f"runtime tree sha mismatch: {actual} != {EXPECTED_RUNTIME_TREE_SHA1}. "
            "Re-check HANDOFF-CODEX-UNIFIED-RUNTIME.md before baking."
        )

    clean_retired_runtime(image)

    for src in sorted(runtime_dir.glob("*.py")):
        if src.name in RETIRED_RUNTIME_FILES:
            continue
        e2copy_file(image, src, f"/usr/lib/carthing/{src.name}", mode="0644")

    # The runtime owns its complete vendored dependency set. Remove the Bumble
    # tree first so a bake cannot retain stale modules from the base image.
    e2rm_tree(image, "/usr/lib/carthing/vendor/bumble")
    copy_overlay_tree(image, runtime_dir / "vendor", "/usr/lib/carthing/vendor")

    # Hardware modules are part of the release overlay too. Copy them
    # explicitly so a bake cannot accidentally depend on whichever modules
    # happened to exist in its base image.
    modules_dir = runtime_dir / "modules"
    if modules_dir.is_dir():
        e2rm_tree(image, "/usr/lib/carthing/modules")
        copy_overlay_tree(image, modules_dir, "/usr/lib/carthing/modules")

    for name in NATIVE_RUNTIME_FILES:
        src = runtime_dir / name
        if src.exists():
            e2copy_file(image, src, f"/usr/lib/carthing/{name}", mode="0755")


def copy_support_files(image: Path) -> None:
    copy_overlay_tree(image, OVERLAY / "usr/libexec/carthing", "/usr/libexec/carthing")
    for name in RETIRED_INIT_FILES:
        e2rm_file(image, f"/etc/init.d/{name}")
    copy_overlay_tree(image, OVERLAY / "etc/init.d", "/etc/init.d")


def verify_image(image: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="carthing-verify-") as tmp_s:
        tmp = Path(tmp_s)
        default_path = tmp / "default-carthing"
        runtime_dir = tmp / "runtime"
        runtime_dir.mkdir()

        e2read_file(image, "/etc/default/carthing", default_path)
        default_text = default_path.read_text()
        required = [
            "CARTHING_RUNTIME_ENTRY=/usr/lib/carthing/carthing_runtime.py",
            "CARTHING_BT_ALIAS=",
            "CARTHING_A2DP_RECEIVER=",
            "CARTHING_A2DP_NAME=",
            "CARTHING_A2DP_AUTOCONNECT=0",
        ]
        missing = [item for item in required if item not in default_text]
        if missing:
            raise SystemExit(f"rootfs default verification failed: missing {missing}")

        for src in sorted((OVERLAY / "usr/lib/carthing").glob("*.py")):
            e2read_file(image, f"/usr/lib/carthing/{src.name}", runtime_dir / src.name)
        actual = runtime_tree_sha1(runtime_dir)
        if actual != EXPECTED_RUNTIME_TREE_SHA1:
            raise SystemExit(f"baked runtime sha mismatch: {actual} != {EXPECTED_RUNTIME_TREE_SHA1}")

        for name in NATIVE_RUNTIME_FILES:
            if (OVERLAY / "usr/lib/carthing" / name).exists() and not e2path_exists(image, f"/usr/lib/carthing/{name}"):
                raise SystemExit(f"native runtime file missing from rootfs: {name}")

        required_vendor = [
            "/usr/lib/carthing/vendor/BUMBLE-VERSION",
            "/usr/lib/carthing/vendor/bumble/_version.py",
            "/usr/lib/carthing/vendor/bumble/pairing.py",
            "/usr/lib/carthing/vendor/bumble/transport/hci_socket.py",
        ]
        missing_vendor = [path for path in required_vendor if not e2path_exists(image, path)]
        if missing_vendor:
            raise SystemExit(f"vendored runtime dependency missing from rootfs: {missing_vendor}")

        required_modules = [
            "/usr/lib/carthing/modules/mfi/apple-mfi-auth.ko",
            "/usr/lib/carthing/modules/mfi/apple-mfi-auth-i2c.ko",
        ]
        missing_modules = [
            path for path in required_modules
            if (OVERLAY / path.lstrip("/")).exists() and not e2path_exists(image, path)
        ]
        if missing_modules:
            raise SystemExit(f"hardware overlay module missing from rootfs: {missing_modules}")

        leaked = [
            name for name in RETIRED_RUNTIME_FILES
            if e2path_exists(image, f"/usr/lib/carthing/{name}")
        ]
        if leaked:
            raise SystemExit(f"retired runtime files leaked into rootfs: {leaked}")

        required_exec = [
            "/usr/libexec/carthing/profilectl",
            "/usr/libexec/carthing/usb-profile",
            "/usr/libexec/carthing/bt-profile",
            "/usr/libexec/carthing/audio-profile",
            "/usr/libexec/carthing/sensor-profile",
            "/usr/libexec/carthing/debug-profile",
        ]
        missing_exec = [path for path in required_exec if not e2path_exists(image, path)]
        if missing_exec:
            raise SystemExit(f"profile tooling missing from rootfs: {missing_exec}")

        required_init = [
            "/etc/init.d/S03-runtime-state",
            "/etc/init.d/S04-usbgadget",
            "/etc/init.d/S05-usbnet",
            "/etc/init.d/S06-ssh",
        ]
        missing_init = [path for path in required_init if not e2path_exists(image, path)]
        if missing_init:
            raise SystemExit(f"early init scripts missing from rootfs: {missing_init}")

        retired_init = [
            name for name in RETIRED_INIT_FILES
            if e2path_exists(image, f"/etc/init.d/{name}")
        ]
        if retired_init:
            raise SystemExit(f"retired init files leaked into rootfs: {retired_init}")

        if not e2path_exists(image, "/etc/init.d/disabled-S50-carthing-remote"):
            raise SystemExit("quarantined manual Bumble launcher missing from rootfs")


def write_manifest(bundle: Path, base_bundle: Path) -> None:
    files = ["bootfs.bin", "rootfs.img", "env.txt", "meta.json"]
    sha_lines = []
    for name in files:
        path = bundle / name
        if path.exists():
            sha_lines.append(f"{sha256(path)}  {name}\n")
    (bundle / "SHA256SUMS").write_text("".join(sha_lines))

    manifest = f"""# Unified runtime flash bundle

Created: {dt.datetime.now().isoformat(timespec="seconds")}
Base bundle: {base_bundle}
Runtime source: {REPO_ROOT}
Runtime tree sha1: {EXPECTED_RUNTIME_TREE_SHA1}

Hardware baseline:
- stock-plus rescue/profile kernel
- 512M rootfs
- default/rescue NCM (`CONFIG_USB_G_NCM=y`) for SSH/recovery after every boot
- optional USB functions are exposed only through profilectl/usb-profile
- USB Audio/Serial/HID/MIDI/Storage are switch targets, not boot defaults
- rootfs bake removes retired runtime files: {", ".join(RETIRED_RUNTIME_FILES)}

This bundle is intended for `scripts/full-flash-bundle.py`.
"""
    (bundle / "README.md").write_text(manifest)


def copy_base_bundle(base: Path, output: Path) -> None:
    required = ["bootfs.bin", "rootfs.img", "env.txt", "meta.json"]
    for name in required:
        src = base / name
        if not src.exists():
            raise SystemExit(f"missing base bundle artifact: {src}")

    output.mkdir(parents=True, exist_ok=False)
    for name in required:
        shutil.copy2(base / name, output / name)
    for optional in ["manual", "boot", "scripts", "ssh"]:
        src = base / optional
        if src.is_dir():
            shutil.copytree(src, output / optional)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-bundle", type=Path, default=DEFAULT_BASE_BUNDLE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base = args.base_bundle.resolve()
    if args.output:
        output = args.output.resolve()
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        output = (REPO_ROOT / f"{DEFAULT_ARTIFACT_PREFIX}-{stamp}").resolve()

    copy_base_bundle(base, output)
    rootfs = output / "rootfs.img"
    copy_runtime(rootfs)
    copy_support_files(rootfs)
    patch_default_carthing(rootfs)
    verify_image(rootfs)
    write_manifest(output, base)

    print(f"bundle: {output}")
    print(f"runtime tree sha1: {EXPECTED_RUNTIME_TREE_SHA1}")
    print("hashes:")
    print((output / "SHA256SUMS").read_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
