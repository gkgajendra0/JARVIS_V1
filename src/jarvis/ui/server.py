"""Single-origin loopback-only HUD server; deliberately no action routes."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jarvis.ui.hub import UISnapshotHub

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def create_ui_server(
    hub: UISnapshotHub, *, port: int = 8765, assets: Path | None = None
) -> ThreadingHTTPServer:
    """Bind only localhost even when invoked from a privileged process."""
    asset_dir = (assets or Path(__file__).parent / "assets").resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args  # Never log potentially sensitive query strings.

        def _headers(self, status: int, mime: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()

        def _send(
            self, status: int, data: bytes = b"", mime: str = "text/plain"
        ) -> None:
            self._headers(status, mime, len(data))
            if self.command != "HEAD":
                self.wfile.write(data)

        def _same_origin(self) -> bool:
            authority = self.headers.get("Host", "")
            allowed = {
                "127.0.0.1",
                "localhost",
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if authority not in allowed:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }

        def _get(self) -> None:
            if not self._same_origin():
                self._send(403)
                return
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == "/api/snapshot":
                data = json.dumps(hub.snapshot(), separators=(",", ":")).encode("utf-8")
                self._send(200, data, "application/json; charset=utf-8")
                return
            if path == "/":
                path = "/index.html"
            if path.startswith("/api/") or "\\" in path or "\x00" in path:
                self._send(404)
                return
            target = (asset_dir / path.lstrip("/")).resolve()
            if not target.is_relative_to(asset_dir) or not target.is_file():
                self._send(404)
                return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), mime)

        def do_GET(self) -> None:
            self._get()

        def do_HEAD(self) -> None:
            self._get()

        def do_POST(self) -> None:
            self._send(405)

        def do_OPTIONS(self) -> None:
            self._send(405)

        def do_PUT(self) -> None:
            self._send(405)

        def do_PATCH(self) -> None:
            self._send(405)

        def do_DELETE(self) -> None:
            self._send(405)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
