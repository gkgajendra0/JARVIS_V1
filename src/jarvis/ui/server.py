"""Local-only read-only HTTP frontend for JARVIS's visual companion."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlsplit

from jarvis.ui.hub import UIEventHub

_ASSET_ROOT = files("jarvis.ui").joinpath("assets")
_MIME = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


class _LocalUIHandler(BaseHTTPRequestHandler):
    server_version = "JarvisUI/1"
    hub: UIEventHub

    def log_message(self, format: str, *args: object) -> None:
        # No query/path/body logs: conservative against private context leakage.
        del format, args

    def _headers(self, status: int, mime: str, size: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()

    def _send(self, status: int, data: bytes, mime: str) -> None:
        self._headers(status, mime, len(data))
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, data: object) -> None:
        self._send(
            200,
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        host = self.headers.get("Host", "").casefold()
        if host not in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }:
            self._send(403, b"Host denied", "text/plain; charset=utf-8")
            return
        url = urlsplit(self.path)
        if url.path == "/api/snapshot":
            self._json(self.hub.snapshot())
            return
        if url.path == "/api/events":
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
                self._json(self.hub.events_after(after))
            except (ValueError, TypeError):
                self._send(400, b"Invalid sequence", "text/plain; charset=utf-8")
            return
        if url.path in {"/", "/index.html"}:
            filename = "index.html"
        elif url.path in {"/ui.css", "/ui.js", "/orb-visual.js"}:
            filename = url.path[1:]
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        path = PurePosixPath(filename)
        if len(path.parts) != 1 or path.name.startswith("."):
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        asset = _ASSET_ROOT.joinpath(filename)
        try:
            data = asset.read_bytes()
        except FileNotFoundError:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        mime = _MIME.get(path.suffix) or mimetypes.guess_type(filename)[0]
        self._send(200, data, mime or "application/octet-stream")

    def do_POST(self) -> None:
        self._send(405, b"Read only", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:
        self.do_POST()

    def do_DELETE(self) -> None:
        self.do_POST()


def create_ui_server(
    hub: UIEventHub | None = None, *, port: int = 8765
) -> ThreadingHTTPServer:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be a valid integer")
    projection = hub if hub is not None else UIEventHub()
    if not isinstance(projection, UIEventHub):
        raise TypeError("hub must be a UIEventHub")
    handler = type("BoundJarvisUIHandler", (_LocalUIHandler,), {"hub": projection})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
