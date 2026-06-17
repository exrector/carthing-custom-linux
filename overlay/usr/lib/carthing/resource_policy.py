"""Mode-aware host resource policy for Car Thing.

This module owns low-level resource knobs that are outside Bluetooth routing:
CPU governor selection and read-only memory/zram diagnostics. It is deliberately
conservative: unsupported sysfs files are treated as proof data, not as errors,
and the policy never changes min/max frequencies.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import operation_mode


logger = logging.getLogger(__name__)


def _truthy(value, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip()
    except Exception:
        return ""


def _write_text(path: Path, value: str) -> bool:
    try:
        path.write_text(value + "\n", encoding="ascii")
        return True
    except Exception as exc:
        logger.debug("resource policy: write %s failed: %s", path, exc)
        return False


def _int_or_none(value: str):
    try:
        return int(str(value).strip())
    except Exception:
        return None


class RuntimeResourcePolicy:
    """Apply and publish mode-owned CPU/memory policy.

    The policy is intentionally small and reversible. Play Now should favor a
    calm scheduler, while Коммутатор can request a faster governor during active
    routing. The actual result is always published so live proof can distinguish
    "requested" from "kernel accepted".
    """

    def __init__(
        self,
        settings=None,
        hw_caps=None,
        cpufreq_root: str = "/sys/devices/system/cpu/cpufreq",
        zram_sysfs: str = "/sys/block/zram0",
    ):
        self.settings = settings
        self.hw_caps = dict(hw_caps or {})
        self.cpufreq_root = Path(cpufreq_root)
        self.zram_sysfs = Path(zram_sysfs)
        self.enabled = _truthy(
            os.environ.get(
                "CARTHING_CPU_POLICY_ENABLE",
                self._setting("cpu_policy_enable", True),
            ),
            True,
        )
        self._last_key = None
        self._last_snapshot = {}
        self._last_refresh = 0.0

    def _setting(self, key: str, default=None):
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    def _policies(self) -> list[Path]:
        try:
            return sorted(
                path for path in self.cpufreq_root.glob("policy*")
                if (path / "scaling_governor").exists()
            )
        except Exception:
            return []

    def _available_governors(self, policy: Path) -> list[str]:
        text = _read_text(policy / "scaling_available_governors")
        return [item.strip("[]") for item in text.split() if item.strip("[]")]

    def _preferred_governors(self, mode: str, tier: str | None) -> list[str]:
        mode = operation_mode.normalize(mode)
        tier = str(tier or "")
        if mode == operation_mode.COMMUTATOR or tier in ("transfer", "pairing"):
            configured = os.environ.get(
                "CARTHING_CPU_GOV_COMMUTATOR",
                self._setting("cpu_governor_commutator", "performance"),
            )
            return [configured, "performance", "schedutil", "ondemand"]
        configured = os.environ.get(
            "CARTHING_CPU_GOV_PLAYNOW",
            self._setting("cpu_governor_playnow", "schedutil"),
        )
        return [configured, "schedutil", "ondemand", "conservative", "powersave", "performance"]

    @staticmethod
    def _select_governor(preferred: list[str], available: list[str]) -> str:
        for governor in preferred:
            if governor and governor in available:
                return governor
        return available[0] if available else ""

    def apply(self, mode: str, tier: str | None = None, reason: str = "") -> dict:
        mode = operation_mode.normalize(mode)
        tier = str(tier or "")
        key = (mode, tier)
        now = time.monotonic()
        if key == self._last_key and now - self._last_refresh < 10.0:
            return dict(self._last_snapshot)
        self._last_key = key
        self._last_refresh = now

        policies = self._policies()
        preferred = self._preferred_governors(mode, tier)
        changed = []
        unsupported = []

        if self.enabled:
            for policy in policies:
                available = self._available_governors(policy)
                target = self._select_governor(preferred, available)
                current = _read_text(policy / "scaling_governor")
                if target and current != target:
                    if _write_text(policy / "scaling_governor", target):
                        changed.append(f"{policy.name}:{current}->{target}")
                    else:
                        unsupported.append(f"{policy.name}:{target}")
                elif not target:
                    unsupported.append(f"{policy.name}:no-supported-governor")

        snapshot = self.snapshot(mode=mode, tier=tier, reason=reason, preferred=preferred)
        snapshot["cpu_policy_enabled"] = self.enabled
        snapshot["cpu_policy_changed"] = changed
        snapshot["cpu_policy_unsupported"] = unsupported
        if changed or unsupported:
            logger.info(
                "resource policy: mode=%s tier=%s reason=%s changed=%s unsupported=%s",
                mode,
                tier or "-",
                reason or "-",
                changed,
                unsupported,
            )
        self._last_snapshot = snapshot
        return dict(snapshot)

    def snapshot(self, mode=None, tier=None, reason="", preferred=None) -> dict:
        mode = operation_mode.normalize(mode or operation_mode.DEFAULT)
        tier = str(tier or "")
        policy_rows = []
        for policy in self._policies():
            available = self._available_governors(policy)
            policy_rows.append(
                {
                    "policy": policy.name,
                    "governor": _read_text(policy / "scaling_governor") or None,
                    "available_governors": available,
                    "cur_freq_khz": _int_or_none(_read_text(policy / "scaling_cur_freq")),
                    "min_freq_khz": _int_or_none(_read_text(policy / "scaling_min_freq")),
                    "max_freq_khz": _int_or_none(_read_text(policy / "scaling_max_freq")),
                }
            )
        return {
            "mode": mode,
            "tier": tier,
            "reason": str(reason or ""),
            "cpu_policy_enabled": self.enabled,
            "cpu_preferred_governors": list(preferred or self._preferred_governors(mode, tier)),
            "cpu_policies": policy_rows,
            "zram": self.zram_status(),
        }

    def zram_status(self) -> dict:
        out = {
            "present": self.zram_sysfs.exists(),
            "active": False,
            "device": "/dev/zram0",
            "disksize_bytes": _int_or_none(_read_text(self.zram_sysfs / "disksize")),
            "algorithm": _read_text(self.zram_sysfs / "comp_algorithm") or None,
            "swap_size_kb": None,
            "swap_used_kb": None,
        }
        try:
            with open("/proc/swaps", "r", encoding="ascii", errors="replace") as fp:
                for line in fp.readlines()[1:]:
                    parts = line.split()
                    if parts and parts[0].endswith("zram0"):
                        out["active"] = True
                        if len(parts) >= 4:
                            out["swap_size_kb"] = _int_or_none(parts[2])
                            out["swap_used_kb"] = _int_or_none(parts[3])
                        break
        except Exception:
            pass
        mm_stat = _read_text(self.zram_sysfs / "mm_stat")
        if mm_stat:
            out["mm_stat"] = mm_stat
        return out
