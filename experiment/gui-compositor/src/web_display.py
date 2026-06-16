"""WebDisplay — браузерный GUI для macOS.

Запускает WebSocket сервер. Открой http://localhost:8765 в браузере.
Кадры идут как base64 PNG через WS. Клики/клавиши — обратно через WS.

DRMDisplayAdapter-совместимый: реализует blit(rgba_bytes).
"""
import asyncio
import base64
import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)

WS_PORT   = 8765
HTTP_PORT = 8766

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Car Thing</title>
<style>
  body { margin:0; background:#111; display:flex; justify-content:center; align-items:center; height:100vh; }
  canvas { cursor:pointer; border:1px solid #333; }
</style>
</head>
<body>
<canvas id="c" width="800" height="480"></canvas>
<script>
const c = document.getElementById('c');
const ctx = c.getContext('2d');
const ws = new WebSocket('ws://localhost:""" + str(WS_PORT) + """');
ws.binaryType = 'blob';

ws.onmessage = e => {
  const img = new Image();
  img.onload = () => { ctx.drawImage(img, 0, 0); URL.revokeObjectURL(img.src); };
  img.src = e.data.text ? ('data:image/png;base64,' + e.data) : URL.createObjectURL(e.data);
};

function send(obj) { if (ws.readyState===1) ws.send(JSON.stringify(obj)); }

c.addEventListener('click',      e => { const r=c.getBoundingClientRect(); send({t:'tap',   x:Math.round(e.clientX-r.left), y:Math.round(e.clientY-r.top)}); });
c.addEventListener('contextmenu',e => { e.preventDefault(); const r=c.getBoundingClientRect(); send({t:'long_tap', x:Math.round(e.clientX-r.left), y:Math.round(e.clientY-r.top)}); });
c.addEventListener('wheel',      e => { send({t: e.deltaY<0 ? 'encoder_cw' : 'encoder_ccw'}); });

let sx=null, sy=null;
c.addEventListener('mousedown', e => { const r=c.getBoundingClientRect(); sx=e.clientX-r.left; sy=e.clientY-r.top; });
c.addEventListener('mouseup',   e => {
  if (sx===null) return;
  const r=c.getBoundingClientRect(); const ex=e.clientX-r.left, ey=e.clientY-r.top;
  const dx=ex-sx, dy=ey-sy;
  if (Math.abs(dx)>80 && Math.abs(dx)>Math.abs(dy)*1.5) send({t: dx<0?'swipe_left':'swipe_right'});
  else if (Math.abs(dy)>80 && Math.abs(dy)>Math.abs(dx)*1.5) send({t: dy<0?'swipe_up':'swipe_down'});
  sx=null;
});

document.addEventListener('keydown', e => {
  const m={ArrowUp:'encoder_cw',ArrowDown:'encoder_ccw',Enter:'press',Escape:'back',s:'settings'};
  if (m[e.key]) { e.preventDefault(); send({t:m[e.key]}); }
});

ws.onopen  = () => console.log('Car Thing connected');
ws.onclose = () => console.log('Car Thing disconnected');
</script>
</body>
</html>
"""


class WebDisplay:
    """Drop-in замена DRMDisplay. Используй как MacDisplay — передай в DRMDisplayAdapter."""

    def __init__(self, ws_port=WS_PORT, http_port=HTTP_PORT):
        self.width  = 800
        self.height = 480
        self._ws_port   = ws_port
        self._http_port = http_port
        self._on_event  = None
        self._clients   = set()
        self._loop      = None
        self._started   = threading.Event()

        t = threading.Thread(target=self._run_servers, daemon=True)
        t.start()
        self._started.wait(timeout=3)
        log.info("WebDisplay ready — open http://localhost:%d", http_port)
        print(f"\n>>> Открой в браузере: http://localhost:{http_port}\n")

    def set_on_event(self, on_event):
        self._on_event = on_event

    def blit(self, rgba_bytes: bytes):
        """Принять RGBA 800×480 bytes (ландшафт, present без поворота), отправить как PNG."""
        if not self._clients or self._loop is None:
            return
        try:
            from PIL import Image
            img = Image.frombytes("RGBA", (800, 480), rgba_bytes)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=False)
            data = base64.b64encode(buf.getvalue()).decode()
            asyncio.run_coroutine_threadsafe(self._broadcast(data), self._loop)
        except Exception as e:
            log.warning("WebDisplay.blit: %s", e)

    async def _broadcast(self, data: str):
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    def _emit(self, event):
        if self._on_event and self._loop:
            asyncio.run_coroutine_threadsafe(
                asyncio.coroutine_to_thread(self._on_event, event)
                if False else self._call_event(event),
                self._loop,
            )

    async def _call_event(self, event):
        try:
            self._on_event(event)
        except Exception as e:
            log.warning("WebDisplay on_event: %s", e)

    def _run_servers(self):
        import asyncio as aio
        loop = aio.new_event_loop()
        aio.set_event_loop(loop)
        self._loop = loop
        loop.run_until_complete(self._async_main())

    async def _async_main(self):
        # HTTP сервер для HTML страницы
        threading.Thread(target=self._http_server, daemon=True).start()

        # WebSocket сервер
        sys_ws = None
        try:
            import sys, os
            # vendor websockets
            vendor = os.path.join(os.path.dirname(__file__), "vendor")
            if vendor not in sys.path:
                sys.path.insert(0, vendor)
            import websockets
            self._started.set()
            async with websockets.serve(self._ws_handler, "localhost", self._ws_port):
                await asyncio.get_running_loop().create_future()  # вечно
        except Exception as e:
            log.error("WebDisplay WS server failed: %s", e)
            self._started.set()

    async def _ws_handler(self, ws):
        log.info("WebDisplay: browser connected")
        self._clients.add(ws)
        try:
            async for msg in ws:
                self._handle_msg(msg)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            log.info("WebDisplay: browser disconnected")

    def _handle_msg(self, msg: str):
        import json
        try:
            data = json.loads(msg)
        except Exception:
            return
        t = data.get("t")
        if t in ("tap", "long_tap"):
            event = (t, data.get("x", 0), data.get("y", 0))
        else:
            event = t
        if event and self._on_event:
            try:
                self._on_event(event)
            except Exception as e:
                log.warning("WebDisplay event dispatch: %s", e)

    def _http_server(self):
        html = _HTML.encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, *a):
                pass  # тихий HTTP лог

        server = HTTPServer(("localhost", self._http_port), Handler)
        server.serve_forever()

    def close(self):
        pass
