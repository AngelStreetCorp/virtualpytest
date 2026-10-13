"""
A private, per-run web server for the emulator page (TASK-33 phase 4c).

Bound to 127.0.0.1 only, it serves:
  GET  /index.html    the emulator page (web/index.html)
  GET  /rom           the owner's ROM (from a private file; a .zip is unpacked in memory)
  GET  /state         the save to resume from (a private file), 404 if none
  POST /state         the page's new save, written to the private save file
  POST /video         the page's recording of the game screen (for the run's game report)
so the ROM and the saves never pass through executor actions, logs or reports. The game page is
opened by the userinterface at http://127.0.0.1:<port>/index.html; the server lives as long as the
script run.
"""

import http.server
import os
import threading
import zipfile

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = 8791


def rom_bytes(path: str) -> bytes:
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return z.read(z.namelist()[0])
    with open(path, "rb") as f:
        return f.read()


class GameServer:
    def __init__(self, rom_path: str, state_in: str, state_out: str, port: int = PORT, video_out: str = ""):
        self.rom = rom_bytes(rom_path)
        self.state_in, self.state_out, self.port = state_in, state_out, port
        self.video_out = video_out
        self.saved = threading.Event()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet: nothing about the ROM or saves in the logs
                pass

            def _send(self, code, body=b"", ctype="application/octet-stream"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    with open(os.path.join(WEB, "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if self.path == "/rom":
                    return self._send(200, server.rom)
                if self.path == "/state":
                    if server.state_in and os.path.exists(server.state_in):
                        with open(server.state_in, "rb") as f:
                            return self._send(200, f.read(), "application/json")
                    return self._send(404)
                return self._send(404)

            def do_POST(self):
                targets = {"/state": server.state_out, "/video": server.video_out}
                if not targets.get(self.path):
                    return self._send(404)
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                fd = os.open(targets[self.path], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(body)
                if self.path == "/state":
                    server.saved.set()
                return self._send(200, b"ok", "text/plain")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/index.html"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
