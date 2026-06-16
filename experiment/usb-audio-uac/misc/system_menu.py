"""Local system mode menu for Car Thing.

The menu is intentionally thin: it delegates the actual policy to profilectl,
so the GUI and boot scripts keep one source of truth for selected profiles.
"""

import os
import shlex


PROFILECTL = os.environ.get("CARTHING_PROFILECTL", "/usr/libexec/carthing/profilectl")


class MenuItem:
    def __init__(self, label, detail, action):
        self.label = label
        self.detail = detail
        self.action = action


class SystemModeMenu:
    def __init__(self, logger=None):
        self.logger = logger
        self.index = 0
        self.message = ""
        self.message_ok = True
        self.items = [
            MenuItem(
                "Normal Mode",
                "NCM + Remote + playback + normal debug",
                lambda: self._set_profiles(
                    [
                        ("usb", "ncm"),
                        ("bt", "remote"),
                        ("audio", "playback"),
                        ("debug", "normal"),
                    ],
                    "Normal mode saved. Restarting runtime...",
                    restart=True,
                ),
            ),
            MenuItem(
                "Remote Control",
                "BLE media remote profile",
                lambda: self._set_profiles(
                    [("bt", "remote"), ("audio", "playback")],
                    "Remote profile saved. Restarting runtime...",
                    restart=True,
                ),
            ),
            MenuItem(
                "Transfer",
                "Phone audio source -> trusted speakers",
                lambda: self._set_profiles(
                    [("bt", "transfer"), ("audio", "bridge")],
                    "Transfer profile saved. Restarting runtime...",
                    restart=True,
                ),
            ),
            MenuItem(
                "Unified BT",
                "Remote + transfer services",
                lambda: self._set_profiles(
                    [("bt", "all"), ("audio", "bridge")],
                    "Unified BT profile saved. Restarting runtime...",
                    restart=True,
                ),
            ),
            MenuItem(
                "USB Rescue NCM",
                "Restore USB network access",
                lambda: self._set_profiles(
                    [("usb", "ncm")],
                    "USB NCM applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB NCM + Audio",
                "Composite USB profile",
                lambda: self._set_profiles(
                    [("usb", "ncm,audio")],
                    "USB audio profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB NCM + Serial",
                "CDC ACM console candidate",
                lambda: self._set_profiles(
                    [("usb", "ncm,serial")],
                    "USB serial profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB NCM + HID",
                "USB keyboard/input candidate",
                lambda: self._set_profiles(
                    [("usb", "ncm,hid")],
                    "USB HID profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB NCM + MIDI",
                "USB MIDI candidate",
                lambda: self._set_profiles(
                    [("usb", "ncm,midi")],
                    "USB MIDI profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB NCM + Storage",
                "Mass-storage candidate",
                lambda: self._set_profiles(
                    [("usb", "ncm,storage")],
                    "USB storage profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "USB Composite All",
                "NCM + audio + serial + HID + MIDI",
                lambda: self._set_profiles(
                    [("usb", "ncm,audio,serial,hid,midi")],
                    "USB composite profile applied.",
                    restart=False,
                ),
            ),
            MenuItem(
                "Debug Normal",
                "HTTP + reverse agent",
                lambda: self._set_profiles(
                    [("debug", "normal")],
                    "Debug normal saved.",
                    restart=False,
                ),
            ),
            MenuItem(
                "Debug Service",
                "HTTP + telnet + beacon",
                lambda: self._set_profiles(
                    [("debug", "service")],
                    "Debug service saved.",
                    restart=False,
                ),
            ),
        ]

    def move(self, delta):
        if not self.items:
            self.index = 0
            return
        step = 1 if delta > 0 else -1
        self.index = (self.index + step) % len(self.items)
        self.message = ""

    def snapshot(self):
        return {
            "index": self.index,
            "items": [
                {"label": item.label, "detail": item.detail}
                for item in self.items
            ],
            "message": self.message,
            "message_ok": self.message_ok,
            "status": self.status_lines(),
        }

    def select(self):
        if not self.items:
            return {"ok": False, "message": "No menu items.", "restart": False}
        item = self.items[self.index]
        ok, message, restart = item.action()
        self.message = message
        self.message_ok = ok
        if self.logger:
            log = self.logger.info if ok else self.logger.error
            log("System menu action: %s -> %s", item.label, message)
        return {"ok": ok, "message": message, "restart": restart}

    def status_lines(self):
        ok, output = self._run([PROFILECTL, "status"], timeout=3)
        if not ok:
            return ["profilectl unavailable"]

        lines = []
        current = None
        values = {}
        for raw in output.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line.strip("[]")
                continue
            if current == "usb" and "usb" not in values:
                values["usb"] = line
                continue
            if line.startswith("profile="):
                values[current or "profile"] = line.split("=", 1)[1]

        for key in ("usb", "bt", "audio", "debug"):
            if key in values:
                lines.append(f"{key.upper()}: {values[key]}")
        return lines or ["profiles: unknown"]

    def _set_profiles(self, pairs, success_message, restart=False):
        errors = []
        for domain, profile in pairs:
            ok, output = self._run([PROFILECTL, domain, "set", profile], timeout=8)
            if not ok:
                errors.append(f"{domain}={profile}: {output}")
        if errors:
            return False, errors[0][:96], False
        return True, success_message, restart

    @staticmethod
    def _run(args, timeout=5):
        del timeout
        log_path = "/run/carthing/system-menu-command.log"
        command = " ".join(shlex.quote(str(arg)) for arg in args)
        rc = os.system(f"{command} > {shlex.quote(log_path)} 2>&1")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                output = handle.read().strip()
        except OSError:
            output = ""

        if os.WIFEXITED(rc):
            exit_code = os.WEXITSTATUS(rc)
        else:
            exit_code = rc
        return exit_code == 0, output or f"exit {exit_code}"
