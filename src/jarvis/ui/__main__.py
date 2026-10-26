"""Offline/no-credentials HUD preview entrypoint."""

from __future__ import annotations

import argparse
import sys
import webbrowser

from jarvis.ui.hub import UISnapshotHub
from jarvis.ui.server import create_ui_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local JARVIS HUD (read-only preview)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        server = create_ui_server(UISnapshotHub(), port=args.port)
    except OSError as exc:
        print(f"Could not start local HUD: {exc}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{args.port}/"
    print(f"JARVIS HUD preview (no runtime): {url}", flush=True)
    try:
        if args.open_browser:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
