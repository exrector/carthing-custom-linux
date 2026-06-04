#!/usr/bin/env python3
"""Verify the vendored Bumble release and its CTKD implementation."""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "overlay/usr/lib/carthing"
sys.path.insert(0, str(RUNTIME / "vendor"))
sys.path.insert(0, str(RUNTIME))

import bumble  # noqa: E402
from bumble.smp import Session  # noqa: E402


EXPECTED_VERSION = "0.0.229"


def reversed_hex(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))[::-1]


def main() -> int:
    if bumble.__version__ != EXPECTED_VERSION:
        raise SystemExit(
            f"Bumble version mismatch: {bumble.__version__} != {EXPECTED_VERSION}"
        )

    ltk = reversed_hex("368df9bc e3264b58 bd066c33 334fbf64")
    link_key = reversed_hex("05040302 01000908 07060504 03020100")
    vectors = [
        (
            Session.derive_link_key(ltk, False),
            reversed_hex("bc1ca4ef 633fc1bd 0d8230af ee388fb0"),
        ),
        (
            Session.derive_link_key(ltk, True),
            reversed_hex("287ad379 dca40253 0a39f1f4 3047b835"),
        ),
        (
            Session.derive_ltk(link_key, False),
            reversed_hex("a813fb72 f1a3dfa1 8a2c9a43 f10d0a30"),
        ),
        (
            Session.derive_ltk(link_key, True),
            reversed_hex("e85e09eb 5eccb3e2 69418a13 3211bc79"),
        ),
    ]
    if any(actual != expected for actual, expected in vectors):
        raise SystemExit("Bumble CTKD test vector mismatch")

    import accessory_orchestrator  # noqa: F401
    import carthing_runtime  # noqa: F401
    import media_remote  # noqa: F401

    print(f"Bumble vendor OK: {bumble.__version__}, CTKD vectors OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
