"""Headless, offline, source-only screenshot checks for the optional HUD.

Run after ``npm run build`` with ``python -m pip install playwright`` and
``python -m playwright install chromium``. Never loads owner credentials.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from jarvis.ui.hub import UISnapshotHub
from jarvis.ui.server import create_ui_server

SIZES = ((3440, 1440), (1920, 1080), (390, 844))


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture JARVIS HUD review screens")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-hud"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    server = create_ui_server(UISnapshotHub(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in SIZES:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                    )
                    errors: list[str] = []
                    page.on(
                        "pageerror", lambda error, bag=errors: bag.append(str(error))
                    )
                    response = page.goto(url, wait_until="networkidle")
                    assert response is not None and response.status == 200
                    page.get_by_role("heading", name="JARVIS.").wait_for()
                    assert page.get_by_text("PREVIEW / NO RUNTIME").is_visible()
                    assert not page.get_by_text("CANONICAL JARVIS").is_visible()
                    page.wait_for_timeout(800)
                    layout = page.evaluate("""() => ({
                        width: window.innerWidth,
                        scroll: document.documentElement.scrollWidth,
                        core: document.querySelector('.core-frame').getBoundingClientRect().toJSON(),
                    })""")
                    assert layout["scroll"] <= layout["width"] + 2, json.dumps(layout)
                    assert layout["core"]["width"] > 260, json.dumps(layout)
                    assert not errors, errors
                    screenshot = args.output / f"jarvis-{width}x{height}.png"
                    page.screenshot(path=str(screenshot), full_page=True)
                    print(f"Captured {screenshot}, viewport={width}x{height}")
                    if width == 1920:
                        page.get_by_role("button", name="GPU: AUTO").click()
                        assert page.get_by_role("button", name="GPU: LOW").is_visible()
                        assert page.get_by_text(
                            "Reactor schematic / low GPU"
                        ).is_visible()
                        page.screenshot(
                            path=str(args.output / "jarvis-low-gpu.png"), full_page=True
                        )
                        page.get_by_role("button", name="FOCUS MODE").click()
                        assert page.get_by_role(
                            "button", name="SHOW PANELS"
                        ).is_visible()
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
