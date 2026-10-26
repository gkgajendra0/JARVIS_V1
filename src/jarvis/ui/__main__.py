"""Run the optional visual companion without starting any cloud clients."""

from __future__ import annotations

import argparse
import webbrowser

from jarvis.ui.server import create_ui_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS read-only context stage")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open localhost UI in the default browser",
    )
    args = parser.parse_args(argv)
    server = create_ui_server(port=args.port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"JARVIS visual companion: {url}")
    print("Standalone preview mode; no live JARVIS data is connected.")
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
