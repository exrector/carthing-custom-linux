"""Render the Now Playing UI to PNG snapshots for local visual review.

Runs without DRM, X, or Bumble — pure Pillow. Output goes to
tests/preview/*.png in landscape (800×480, the same orientation the UI
draws in before rotation for the framebuffer).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "overlay" / "usr" / "lib" / "carthing"))

os.environ.setdefault("CARTHING_FONT_PATH", "/System/Library/Fonts/Helvetica.ttc")

from PIL import Image

import now_playing_ui as ui_mod


class _PILBackend:
    """Captures the rendered (rotated) frame for snapshotting."""
    def __init__(self):
        self.last_landscape = None

    def blit(self, raw):
        # raw is the BGRX framebuffer in portrait (480×800). Convert back to
        # landscape for review by rotating +90.
        portrait = Image.frombytes("RGBX", (480, 800), raw, "raw", "BGRX")
        self.last_landscape = portrait.rotate(90, expand=True).convert("RGB")


class _FakeState:
    def __init__(self, title="", artist="", duration=0, position=0, playing=False):
        self.title = title
        self.artist = artist
        self.duration = duration
        self.position = position
        self.playing = playing
        self.volume = 0.4


def render_case(name, configure):
    backend = _PILBackend()
    ui = ui_mod.NowPlayingUI(backend)
    configure(ui)
    out = REPO / "tests" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    backend.last_landscape.save(path)
    print(f"  wrote {path}")


def case_clock_only(ui):
    ui.set_clock("14:23")
    ui.render(_FakeState())


def case_now_playing(ui):
    ui.set_clock("14:23")
    state = _FakeState(
        title="Поезд в огне",
        artist="Аквариум",
        duration=312,
        position=87,
        playing=True,
    )
    ui.render(state)


def case_long_title(ui):
    ui.set_clock("23:59")
    state = _FakeState(
        title="A Day in the Life — Remastered 2009 Stereo Mix from Sgt. Pepper",
        artist="The Beatles",
        duration=337,
        position=120,
        playing=True,
    )
    ui.render(state)


def case_imessage_notif(ui):
    ui.set_clock("14:23")
    state = _FakeState(title="Поезд в огне", artist="Аквариум",
                       duration=312, position=87, playing=True)
    ui.show_notification(
        category="Social",
        app_id="iMessage",
        title="Жена",
        message="Купи молока и хлеб по дороге домой пожалуйста",
        ttl_seconds=999,
    )
    ui.render(state)


def case_email_notif(ui):
    ui.set_clock("09:12")
    state = _FakeState()
    ui.show_notification(
        category="Email",
        app_id="Mail",
        title="Boss: Q3 report due Friday",
        message="Please send the consolidated figures by end of week, including all subsidiaries",
        ttl_seconds=999,
    )
    ui.render(state)


def case_incoming_call(ui):
    ui.set_clock("17:45")
    state = _FakeState()
    ui.show_notification(
        category="IncomingCall",
        app_id="Phone",
        title="Mom",
        message="+1 (555) 234-1290",
        ttl_seconds=999,
    )
    ui.render(state)


def main():
    cases = [
        ("01-clock-only", case_clock_only),
        ("02-now-playing", case_now_playing),
        ("03-long-title", case_long_title),
        ("04-imessage", case_imessage_notif),
        ("05-email", case_email_notif),
        ("06-incoming-call", case_incoming_call),
    ]
    print(f"Rendering {len(cases)} cases...")
    for name, configure in cases:
        render_case(name, configure)
    print("Done.")


if __name__ == "__main__":
    main()
