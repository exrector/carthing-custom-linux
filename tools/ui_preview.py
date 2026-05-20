#!/usr/bin/env python3
"""Dev-Mac preview harness for the Car Thing GUI. Renders composited desktops
(status bar + dots + content) to PNGs. NOT shipped to the device.

    python3 tools/ui_preview.py     # -> tools/previews/*.png
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "overlay", "usr", "lib", "carthing")))

from ui_screen import Compositor, PreviewDisplay     # noqa: E402
from ui_statusbar import StatusBar                    # noqa: E402
from ui_anim import AnimDriver                         # noqa: E402
from screens import NowPlayingScreen, MacOSScreen, SettingsScreen  # noqa: E402


class FakeState:
    clock_text = "14:32"
    iphone_connected = True
    mac_connected = False
    unread_count = 0
    title = "Телепортация звука с помощью звуковых анклавов"
    artist = "СИНТЕТИК"
    duration = 757
    position = 192
    playing = True


def main():
    disp = PreviewDisplay(os.path.join(HERE, "previews"))
    st = FakeState()
    comp = Compositor(disp, [NowPlayingScreen(st), MacOSScreen(st), SettingsScreen()],
                      status_bar=StatusBar(), anim=AnimDriver(), state=st)

    for i in range(len(comp.screens)):
        comp.active = i
        print("wrote", comp.render())

    # now-playing with an unread message -> pulsing indicator in status bar
    st.unread_count = 2
    comp.active = 0
    disp.present(_compose(comp), name="nowplaying_unread")
    print("wrote nowplaying_unread.png")

    # settings with the "Дисплей" group expanded
    comp.active = 2
    comp.screens[2].expanded.add("display")
    comp.screens[2].sel = 3
    disp.present(_compose(comp), name="settings_expanded")
    print("wrote settings_expanded.png")

    # lost-contact state on desktop 1
    st.iphone_connected = False
    comp.active = 0
    disp.present(_compose(comp), name="nowplaying_lostcontact")
    print("wrote nowplaying_lostcontact.png")


def _compose(comp):
    from PIL import ImageDraw
    comp._regions.clear()
    img = comp.current.render(comp._regions)
    draw = ImageDraw.Draw(img)
    comp.status_bar.render(draw, comp._regions, comp.anim, comp.state)
    if len(comp.screens) > 1:
        comp._draw_dots(draw)
    return img


if __name__ == "__main__":
    main()
