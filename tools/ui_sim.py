#!/usr/bin/env python3
"""Interactive Car Thing UI simulator (dev-Mac only).

Renders the real Compositor/screens with PIL and serves the frame to a browser
viewport over localhost. Keyboard + clicks map to device inputs. This is a DEV
TOOL — the browser is only a viewport for the PIL frames; the device GUI remains
PIL→DRM. No extra dependencies (stdlib http.server + Pillow).

    python3 tools/ui_sim.py        # then open http://localhost:8723

Keys:  ←/→ switch desktop · ↑/↓ encoder · Enter/Space select · Esc back
       1-4 buttons · click = tap · n = toggle notification · p = play/pause
"""
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mac_music   # native Apple Music capture/control (tools/, dev-Mac only)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "overlay", "usr", "lib", "carthing")))

from ui_screen import Compositor, Display, Input          # noqa: E402
from ui_statusbar import StatusBar                          # noqa: E402
from ui_anim import AnimDriver                              # noqa: E402
from screens import NowPlayingScreen, MacOSScreen, SettingsScreen, PairingModal  # noqa: E402
from app_state import AppState                              # noqa: E402
from intents import Dispatcher                              # noqa: E402

PORT = 8723


class _Sink(Display):
    """Holds the latest composed frame instead of writing PNG."""
    def __init__(self):
        self.img = None

    def present(self, img, name=None):
        self.img = img
        return None


sink = _Sink()
anim = AnimDriver()
_lock = threading.Lock()
calib_rect = None      # (x0,y0,x1,y1) occlusion zone marked by the user

state = AppState()
state.clock_text = "14:32"
# iPhone: connected, playing
state.iphone.connected = True
state.iphone.title = "Телепортация звука с помощью звуковых анклавов"
state.iphone.artist = "СИНТЕТИК"
state.iphone.duration = 757
state.iphone.position = 192
state.iphone.playing = True
# Mac: LIVE from real Apple Music on this Mac (filled by the poller below)
state.mac.connected = False


def _on_command(src, cmd):
    print(f"[device] {src} <- {cmd}", flush=True)
    if src == "mac":
        mac_music.control(cmd)        # actually drive Apple Music on this Mac


dispatcher = Dispatcher(state, on_command=_on_command)

comp = Compositor(
    sink,
    [NowPlayingScreen(emit=dispatcher.dispatch),
     MacOSScreen(emit=dispatcher.dispatch),
     SettingsScreen(on_select=lambda key: dispatcher.dispatch("settings_select", key))],
    status_bar=StatusBar(), anim=anim, state=state, on_intent=dispatcher.dispatch,
    pairing_modal=PairingModal(emit=dispatcher.dispatch))
comp.broadcast_state(state)


def _poll_music():
    """Reflect real Apple Music into the Mac session (D2) every ~2s."""
    while True:
        info = mac_music.read()
        with _lock:
            m = state.mac
            if info.get("connected"):
                m.connected = True
                m.title = info.get("title", "")
                m.artist = info.get("artist", "")
                m.album = info.get("album", "")
                m.duration = info.get("duration", 0)
                m.position = info.get("position", 0)
                m.playing = info.get("playing", False)
            else:
                m.connected = False
        time.sleep(2)


threading.Thread(target=_poll_music, daemon=True).start()


def _overlay_calib(img):
    """Dev-only: show (a) the provisional occlusion dead-zone always, and
    (b) the user's freshly-marked calibration rect (brighter)."""
    import ui_theme as T
    from PIL import Image, ImageDraw
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    # persistent provisional dead-zone (so content can be seen avoiding it)
    ox0, oy0, ox1, oy1 = T.OCCLUSION
    od.rectangle([ox0, oy0, ox1, oy1], fill=(200, 60, 60, 55), outline=(160, 70, 60, 200), width=1)
    od.text((ox0 - 150, oy1 - 16), "occluded (dial/button)", fill=(200, 120, 110, 220))
    if calib_rect:
        x0, y0, x1, y1 = calib_rect
        od.rectangle([x0, y0, x1, y1], fill=(220, 60, 60, 90), outline=(255, 90, 70, 255), width=3)
        od.text((x0 + 6, max(0, y0 + 6)),
                f"mark {int(x1-x0)}x{int(y1-y0)} @ ({int(x0)},{int(y0)})", fill=(255, 230, 230, 255))
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


def _frame_png():
    with _lock:
        anim.tick()
        anim.set_pulsing(state.unread_count > 0)
        comp.render()
        img = _overlay_calib(sink.img)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


KEYMAP = {
    "ArrowRight": Input.SWIPE_LEFT,    # next desktop
    "ArrowLeft": Input.SWIPE_RIGHT,    # prev desktop
    "ArrowDown": Input.ENCODER_CW,
    "ArrowUp": Input.ENCODER_CCW,
    "Enter": Input.PRESS,
    " ": Input.PRESS,
    "Escape": Input.BACK,
    "1": Input.BTN_1, "2": Input.BTN_2, "3": Input.BTN_3, "4": Input.BTN_4,
}


def _handle(msg):
    global calib_rect
    with _lock:
        a = msg.get("action")
        if a == "calib_rect":
            x0, y0 = min(msg["x0"], msg["x1"]), min(msg["y0"], msg["y1"])
            x1, y1 = max(msg["x0"], msg["x1"]), max(msg["y0"], msg["y1"])
            calib_rect = (int(x0), int(y0), int(x1), int(y1))
            print(f"[calib] occlusion rect = {calib_rect}  "
                  f"size={calib_rect[2]-calib_rect[0]}x{calib_rect[3]-calib_rect[1]}", flush=True)
            return
        if a == "calib_clear":
            calib_rect = None
            print("[calib] cleared", flush=True)
            return
        if a == "key":
            key = msg.get("key")
            if key == "n":
                state.unread_count = 0 if state.unread_count else 2
                comp.render()
            elif key == "p":
                dispatcher.dispatch("media_play_pause")   # acts on control source
                comp.render()
            elif key == "m":
                state.mac.connected = not state.mac.connected
                comp.render()
            elif key == "i":
                state.iphone.connected = not state.iphone.connected
                comp.render()
            elif key in KEYMAP:
                comp.handle_input(KEYMAP[key])
        elif a == "tap":
            comp.handle_input((Input.TAP, int(msg["x"]), int(msg["y"])))


PAGE = """<!doctype html><html><head><meta charset=utf-8><title>Car Thing Sim</title>
<style>body{background:#111;margin:0;display:flex;flex-direction:column;align-items:center;
font-family:-apple-system,Arial;color:#888}
.wrap{position:relative;margin-top:24px;width:800px;height:480px;border:1px solid #333}
#s,#c{position:absolute;left:0;top:0;width:800px;height:480px}
#s{image-rendering:pixelated}#c{cursor:crosshair}
.k{margin:12px;font-size:13px;line-height:1.7}#m{color:#ff7a66;height:16px;font-size:13px}</style>
</head><body>
<div class=wrap><img id=s src="/frame.png"><canvas id=c width=800 height=480></canvas></div>
<div id=m></div>
<div class=k>←/→ столы&nbsp;·&nbsp;↑/↓ энкодер&nbsp;·&nbsp;Enter выбор&nbsp;·&nbsp;Esc назад&nbsp;·&nbsp;1-4 кнопки&nbsp;·&nbsp;клик=тап&nbsp;·&nbsp;n уведомл.&nbsp;·&nbsp;p play&nbsp;·&nbsp;<b>c=калибровка</b></div>
<script>
const img=document.getElementById('s'),cv=document.getElementById('c'),ctx=cv.getContext('2d');
let calib=false,drag=null;
function setMode(){cv.style.pointerEvents=calib?'auto':'none';
 document.getElementById('m').textContent=calib?'КАЛИБРОВКА: обведи перекрытую зону мышью · x=сброс · c=выход':'';}
setMode();
function refresh(){img.src='/frame.png?t='+Date.now()}
setInterval(refresh,120);
function post(m){fetch('/input',{method:'POST',body:JSON.stringify(m)}).then(refresh)}
function pos(e){const r=cv.getBoundingClientRect();
 return [(e.clientX-r.left)*800/r.width,(e.clientY-r.top)*480/r.height];}
document.addEventListener('keydown',e=>{
 if(e.key==='c'){calib=!calib;setMode();return;}
 if(e.key==='x'&&calib){post({action:'calib_clear'});return;}
 post({action:'key',key:e.key});
 if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' '].includes(e.key))e.preventDefault();});
img.addEventListener('click',e=>{if(calib)return;const r=img.getBoundingClientRect();
 post({action:'tap',x:(e.clientX-r.left)*800/r.width,y:(e.clientY-r.top)*480/r.height});});
cv.addEventListener('mousedown',e=>{const [x,y]=pos(e);drag={x0:x,y0:y,x1:x,y1:y};});
cv.addEventListener('mousemove',e=>{if(!drag)return;const [x,y]=pos(e);drag.x1=x;drag.y1=y;
 const rx=Math.min(drag.x0,drag.x1),ry=Math.min(drag.y0,drag.y1),w=Math.abs(drag.x1-drag.x0),h=Math.abs(drag.y1-drag.y0);
 ctx.clearRect(0,0,800,480);ctx.fillStyle='rgba(220,60,60,0.25)';ctx.strokeStyle='#ff5a46';ctx.lineWidth=2;
 ctx.fillRect(rx,ry,w,h);ctx.strokeRect(rx,ry,w,h);});
cv.addEventListener('mouseup',e=>{if(!drag)return;const d=drag;drag=null;ctx.clearRect(0,0,800,480);
 post({action:'calib_rect',x0:d.x0,y0:d.y0,x1:d.x1,y1:d.y1});});
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/frame.png"):
            data = _frame_png()
            self.send_response(200); self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store"); self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers(); self.wfile.write(PAGE.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            _handle(json.loads(self.rfile.read(n) or b"{}"))
        except Exception as e:
            print("input error:", e, flush=True)
        self.send_response(204); self.end_headers()


if __name__ == "__main__":
    print(f"Car Thing UI sim → http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
