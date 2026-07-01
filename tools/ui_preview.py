#!/usr/bin/env python3
"""Dev-Mac static PNG previews of the composited desktops. NOT shipped.
For interactive testing use tools/ui_sim.py instead.

    python3 tools/ui_preview.py     # -> tools/previews/*.png
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "overlay", "usr", "lib", "carthing")))

from ui_screen import Compositor, PreviewDisplay     # noqa: E402
from ui_statusbar import StatusBar                    # noqa: E402
from ui_anim import AnimDriver                         # noqa: E402
from screens import (  # noqa: E402
    AssistantScreen,
    NotificationsScreen,
    NowPlayingScreen,
    PluginDashboardScreen,
    SettingsScreen,
)
from app_state import AppState                         # noqa: E402


def _state():
    s = AppState()
    s.clock_text = "14:32"
    s.iphone.connected = True
    s.iphone.title = "Телепортация звука с помощью звуковых анклавов"
    s.iphone.artist = "СИНТЕТИК"
    s.iphone.duration = 757
    s.iphone.position = 192
    s.iphone.playing = True
    s.plugin_catalog = [
        {
            "manifest": {
                "id": "dev.carthing.example.mac-deck",
                "name": "Mac Deck",
            },
            "enabled": True,
        },
        {
            "manifest": {
                "id": "dev.carthing.example.currency",
                "name": "Currency",
            },
            "enabled": True,
        },
        {
            "manifest": {
                "id": "dev.carthing.example.weather",
                "name": "Weather",
            },
            "enabled": True,
        },
    ]
    s.plugin_snapshots = {
        "dev.carthing.example.mac-deck": {
            "cards": [{
                "id": "main-1",
                "title": "MAC DECK",
                "subtitle": "",
                "status": "READY",
                "rows": [],
                "actions": [
                    {
                        "id": "finder",
                        "label": "FINDER",
                        "style": "primary",
                        "enabled": True,
                    },
                    {
                        "id": "music",
                        "label": "MUSIC",
                        "style": "normal",
                        "enabled": True,
                    },
                    {
                        "id": "notes",
                        "label": "NOTES",
                        "style": "normal",
                        "enabled": True,
                    },
                ],
            }, {
                "id": "main-2",
                "title": "MAC DECK",
                "subtitle": "",
                "status": "READY",
                "rows": [],
                "actions": [
                    {
                        "id": "safari",
                        "label": "SAFARI",
                        "style": "normal",
                        "enabled": True,
                    },
                    {
                        "id": "calendar",
                        "label": "CALENDAR",
                        "style": "normal",
                        "enabled": True,
                    },
                    {
                        "id": "mail",
                        "label": "MAIL",
                        "style": "normal",
                        "enabled": True,
                    },
                    {
                        "id": "terminal",
                        "label": "TERMINAL",
                        "style": "normal",
                        "enabled": True,
                    },
                ],
            }],
        },
        "dev.carthing.example.currency": {
            "cards": [{
                "id": "rates",
                "title": "КУРС ЦБ",
                "subtitle": "рублей за единицу",
                "status": "01.07.2026",
                "accent": "#FFAA00",
                "rows": [
                    {"label": "USD", "value": "78.27"},
                    {"label": "EUR", "value": "89.27"},
                ],
                "actions": [],
            }],
        },
        "dev.carthing.example.weather": {
            "cards": [{
                "id": "weather",
                "title": "МОСКВА",
                "subtitle": "Open-Meteo",
                "status": "06:45",
                "accent": "#66CCFF",
                "rows": [
                    {"label": "СЕЙЧАС", "value": "20°"},
                    {"label": "", "value": "Ясно · 22°"},
                ],
                "actions": [],
            }],
        },
    }
    return s


def main():
    disp = PreviewDisplay(os.path.join(HERE, "previews"))
    st = _state()
    comp = Compositor(disp, [
        NowPlayingScreen(),
        SettingsScreen(),
        NotificationsScreen(),
        AssistantScreen(),
        PluginDashboardScreen(),
    ],
                      status_bar=StatusBar(), anim=AnimDriver(), state=st)
    comp.broadcast_state(st)

    for i in range(len(comp.screens)):
        comp.active = i
        st.active_desktop = i
        print("wrote", comp.render())

    st.unread_count = 2
    comp.active = 0
    st.active_desktop = 0
    disp.present(_compose(comp), name="nowplaying_unread")
    print("wrote nowplaying_unread.png")

def _compose(comp, guide=True):
    from PIL import ImageDraw
    import ui_theme as T
    comp._regions.clear()
    img = comp.current.render(comp._regions)
    draw = ImageDraw.Draw(img)
    T.encoder_arc(draw)
    comp.status_bar.render(img, comp._regions, comp.anim, comp.state)
    if len(comp.screens) > 1:
        comp._draw_dots(draw)
    img = T.postprocess(img)
    draw = ImageDraw.Draw(img)
    if guide:
        draw.line([T.CONTENT_X1, 0, T.CONTENT_X1, T.OCCLUSION_BOTTOM], fill=(60, 30, 30), width=1)
    return img


if __name__ == "__main__":
    main()
