#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import sys


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} path={parsed.path} params={params}\n"
        sys.stdout.write(line)
        sys.stdout.flush()
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    host = "0.0.0.0"
    port = 8099
    server = HTTPServer((host, port), Handler)
    print(f"debug beacon server listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
