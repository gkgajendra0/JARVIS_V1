"""UI contract tests: presentation is disposable and never execution authority."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jarvis.ui.hub import UIEventHub
from jarvis.ui.server import create_ui_server


def test_ambient_is_empty_and_offline_until_runtime_attaches() -> None:
    hub = UIEventHub()
    snapshot = hub.snapshot()
    assert snapshot["schema"] == 1
    assert snapshot["runtime_connected"] is False
    assert snapshot["voice_state"] == "offline"
    assert snapshot["panels"] == []
    assert snapshot["work"] == []


def test_voice_is_runtime_owned_and_event_sequence_is_ordered() -> None:
    hub = UIEventHub()
    hub.set_voice_state("speaking")
    assert hub.snapshot()["voice_state"] == "offline"
    hub.set_runtime_connected(True)
    hub.set_voice_state("listening")
    hub.set_voice_state("thinking")
    hub.set_voice_state("speaking")
    assert hub.snapshot()["voice_state"] == "speaking"
    events = hub.events_after(0)
    assert [event["seq"] for event in events["events"]] == [1, 2, 3, 4]
    assert events["requires_snapshot"] is False
    assert hub.events_after(3)["events"][0]["type"] == "voice.state"
    hub.set_runtime_connected(False)
    assert hub.snapshot()["voice_state"] == "offline"


def test_bounded_panels_expire_without_creating_memory_or_authority() -> None:
    now = [100.0]
    hub = UIEventHub(clock=lambda: now[0])
    hub.show_panel(
        panel_id="topic.research",
        panel_type="research",
        title="Research",
        summary="Grounded text only",
        ttl_seconds=3,
    )
    assert len(hub.snapshot()["panels"]) == 1
    now[0] = 102.0
    assert len(hub.snapshot()["panels"]) == 1
    now[0] = 103.0
    assert hub.snapshot()["panels"] == []
    hub.dismiss_panel("topic.research")
    assert hub.events_after(1)["events"] == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("panel_id", "../bad"),
        ("panel_type", "private_memory"),
        ("source", "user_uploaded_html"),
        ("summary", "A" * 501),
        ("priority", 8),
        ("ttl_seconds", 3601),
    ],
)
def test_untrusted_panel_inputs_are_rejected(field: str, replacement: object) -> None:
    values: dict[str, object] = {
        "panel_id": "p.safe",
        "panel_type": "system",
        "title": "System",
        "summary": "Safe status",
    }
    values[field] = replacement
    hub = UIEventHub()
    with pytest.raises((ValueError, TypeError)):
        hub.show_panel(**values)  # type: ignore[arg-type]
    assert not hub.snapshot()["panels"]


def test_topic_detection_never_returns_raw_user_transcript() -> None:
    hub = UIEventHub()
    private_phrase = "my totally secret document"
    hub.observe_accepted_user_text("Jarvis, show my repository and " + private_phrase)
    snapshot = hub.snapshot()
    assert len(snapshot["panels"]) == 1
    assert snapshot["panels"][0]["type"] == "document"
    assert private_phrase not in json.dumps(snapshot)


def test_canonical_work_projection_omits_payloads_and_handles_failures() -> None:
    hub = UIEventHub()
    hub.attach_work_provider(
        lambda: [{"id": "w1", "kind": "research", "state": "running"}]
    )
    assert hub.snapshot()["work"] == []
    hub.set_runtime_connected(True)
    assert hub.snapshot()["work"] == [
        {"id": "w1", "kind": "research", "state": "running"}
    ]

    def unavailable() -> list[dict[str, str]]:
        raise RuntimeError("work unavailable")

    hub.attach_work_provider(unavailable)
    assert hub.snapshot()["work"] == []


def test_event_overflow_signals_fresh_snapshot_needed() -> None:
    hub = UIEventHub(event_limit=4)
    hub.set_runtime_connected(True)
    for index in range(8):
        hub.show_panel(
            panel_id=f"task.{index}",
            panel_type="work",
            title="Work",
            summary="Test",
        )
    events = hub.events_after(1)
    assert events["requires_snapshot"] is True
    assert len(events["events"]) == 4
    with pytest.raises(ValueError):
        hub.events_after(-1)


@pytest.fixture
def ui_http():
    hub = UIEventHub()
    server = create_ui_server(hub, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield hub, f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3.0)


def test_http_serves_only_local_read_only_resources(ui_http) -> None:
    hub, url = ui_http
    with urlopen(url) as response:
        html = response.read().decode("utf-8")
        assert "JARVIS" in html
        assert "orbCanvas" in html
        assert response.headers["Content-Security-Policy"].startswith("default-src")
    for asset in ("ui.css", "ui.js"):
        with urlopen(url + asset) as response:
            assert len(response.read()) > 100
            assert response.headers["Cache-Control"] == "no-store"
    with urlopen(url + "api/snapshot") as response:
        payload = json.load(response)
        assert payload["runtime_connected"] is False
    hub.set_runtime_connected(True)
    with urlopen(url + "api/events?after=0") as response:
        events = json.load(response)
        assert events["events"][0]["type"] == "runtime.connection"
    for path in ("../../README.md", "src/jarvis/config.py", ".git/config"):
        with pytest.raises(HTTPError) as failure:
            urlopen(url + path)
        assert failure.value.code == 404
    with pytest.raises(HTTPError) as failure:
        urlopen(Request(url + "api/snapshot", method="POST", data=b"{}"))
    assert failure.value.code == 405
    with pytest.raises(HTTPError) as failure:
        urlopen(Request(url, headers={"Host": "evil.example"}))
    assert failure.value.code == 403
    with pytest.raises(HTTPError) as failure:
        urlopen(url + "api/events?after=-1")
    assert failure.value.code == 400


def test_ui_browser_smoke_and_animated_canvas(ui_http) -> None:
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    _, url = ui_http
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium unavailable on this machine: {type(exc).__name__}")
        try:
            page = browser.new_page(viewport={"width": 3440, "height": 1440})
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(url, wait_until="domcontentloaded")
            page.locator("#orbCanvas").wait_for(state="visible")
            assert page.locator(".context-card").count() == 0
            assert "PREVIEW" in page.locator("#connectionBadge").inner_text()
            assert page.evaluate(
                "() => document.querySelector('#orbCanvas').width > 100"
            )
            page.locator("#visualCommand").fill("show tasks")
            page.locator("#showPanelButton").click()
            assert page.locator(".context-card").count() == 1
            page.get_by_label("Pin panel").click()
            assert page.get_by_label("Unpin panel").count() == 1
            page.locator("#backHome").click()
            assert page.locator(".context-card").count() == 1
            page.get_by_label("Dismiss panel").click()
            assert page.locator(".context-card").count() == 0
            page.locator("#previewButton").click()
            assert "DEMO" in page.locator("#connectionBadge").inner_text()
            assert page.locator(".context-card").count() == 2
            page.locator("#previewButton").click()
            assert page.locator(".context-card").count() == 0
            assert not errors, errors
            # On reduced-motion systems the globe remains visible but stops
            # continuous animation.
            page.emulate_media(reduced_motion="reduce")
            assert page.locator("#orbCanvas").is_visible()
        finally:
            browser.close()
