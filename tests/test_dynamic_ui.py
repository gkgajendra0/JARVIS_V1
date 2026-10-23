"""UI contract tests: presentation is disposable and never execution authority."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
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



def test_ui_renders_real_diagnostic_feeds_without_frames_or_secrets() -> None:
    hub = UIEventHub()
    hub.set_runtime_connected(True)
    hub.attach_vision_provider(
        lambda: {
            "running": True,
            "active_source": "lenovo",
            "available_sources": ["lenovo", "pocket3"],
            "raw_frame": "must not escape",
            "face_embedding": "must not escape",
        }
    )
    hub.attach_health_provider(
        lambda: [
            {"component": "runtime.voice", "state": "healthy", "metadata": "secret"},
            {"component": "vision.base", "state": "degraded"},
        ]
    )
    payload = hub.snapshot()
    assert payload["vision"] == {
        "connected": True,
        "running": True,
        "active_source": "lenovo",
        "available_sources": ["lenovo", "pocket3"],
    }
    assert payload["health"] == [
        {"component": "runtime.voice", "state": "healthy"},
        {"component": "vision.base", "state": "degraded"},
    ]
    serialized = json.dumps(payload)
    assert "raw_frame" not in serialized
    assert "face_embedding" not in serialized
    assert "secret" not in serialized


def test_research_projection_strips_sensitive_queries_and_untrusted_urls() -> None:
    hub = UIEventHub()
    hub.set_runtime_connected(True)
    hub.show_research_result(
        {
            "ok": True,
            "query": "PRIVATE SEARCH TEXT SHOULD NEVER APPEAR",
            "sources": [
                {
                    "title": "Official technical documentation",
                    "url": "https://docs.python.org/3/reference/?q=PRIVATE_QUERY#fragment",
                    "excerpt": "SECRET EXCERPT",
                },
                {"title": "Local file", "url": "file:///C:/secret.txt"},
                {"title": "Local IP", "url": "https://192.168.1.100/admin"},
                {"title": "Javascript attack", "url": "javascript:alert(1)"},
                {"title": "Internal", "url": "https://host.internal/secret"},
            ],
        }
    )
    panel = hub.snapshot()["panels"][0]
    assert panel["source"] == "research_result"
    assert len(panel["sources"]) == 1
    assert panel["sources"][0]["url"] == "https://docs.python.org/3/reference/"
    assert "PRIVATE" not in json.dumps(panel)
    assert "SECRET" not in json.dumps(panel)
    before = hub.snapshot()["seq"]
    hub.show_research_result({"ok": False, "sources": []})
    assert hub.snapshot()["seq"] == before



def test_ui_capability_result_observer_is_status_only(monkeypatch) -> None:
    from types import SimpleNamespace

    from jarvis.ui import runtime as ui_runtime

    hub = UIEventHub()
    hub.set_runtime_connected(True)
    monkeypatch.setattr(ui_runtime, "_active", SimpleNamespace(hub=hub))
    ui_runtime.observe_capability_result(
        SimpleNamespace(
            status=SimpleNamespace(value="succeeded"),
            capability_key="windows:desktop.control",
            operation="open_secret_file",
            data={"private": "confidential text"},
            reason="hidden operation detail",
        )
    )
    cards = hub.snapshot()["panels"]
    assert len(cards) == 1
    assert cards[0]["title"] == "Recent Jarvis action"
    assert "windows" in cards[0]["summary"]
    assert "succeeded" in cards[0]["summary"]
    assert "confidential" not in json.dumps(cards)
    assert "secret" not in json.dumps(cards)
    assert "hidden" not in json.dumps(cards)


def test_live_diagnostic_adapter_uses_canonical_read_only_interfaces(monkeypatch) -> None:
    from types import SimpleNamespace

    from jarvis.ui import runtime as ui_runtime

    hub = UIEventHub()
    hub.set_runtime_connected(True)
    monkeypatch.setattr(ui_runtime, "_active", SimpleNamespace(hub=hub))

    class Vision:
        running = True

        def report(self, *, event_limit=0):
            assert event_limit == 0
            return {
                "camera": {
                    "active_source": "lenovo",
                    "available_sources": ["lenovo", "pocket3"],
                },
                "private_tracking": "not released",
            }

    class Awareness:
        def system_snapshot(self, *, health_surface_only=False):
            assert health_surface_only
            return [
                SimpleNamespace(
                    descriptor=SimpleNamespace(component_id="runtime.voice"),
                    health=SimpleNamespace(
                        state=SimpleNamespace(value="healthy")
                    ),
                )
            ]

    ui_runtime.attach_diagnostics_projection(
        vision_service=Vision(), self_awareness=Awareness()
    )
    projection = hub.snapshot()
    assert projection["vision"]["active_source"] == "lenovo"
    assert projection["health"] == [
        {"component": "runtime.voice", "state": "healthy"}
    ]
    assert "private_tracking" not in json.dumps(projection)



def test_research_tool_publishes_only_after_real_warranted_result() -> None:
    import asyncio
    from datetime import UTC, datetime

    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.knowledge.research import (
        CurrentResearchService,
        EvidenceSource,
        ProviderResearchEvidence,
    )
    from jarvis.voice.research_tools import ResearchAgentTools

    class LocalProvider:
        provider_name = "synthetic-no-network"
        model_name = "none"

        def research(self, query, mode):
            assert query == "Python documentation"
            return ProviderResearchEvidence(
                sources=(
                    EvidenceSource(
                        source_id="synthetic-docs",
                        url="https://docs.python.org/3/",
                        title="Python Language Reference",
                        domain="docs.python.org",
                        retrieved_at=datetime.now(UTC),
                    ),
                )
            )

        def close(self):
            pass

    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(
        ConversationRole.USER, "Jarvis, search the web for Python documentation"
    )
    observed: list[dict[str, object]] = []
    tools = ResearchAgentTools(
        CurrentResearchService(LocalProvider()),
        conversation,
        result_observer=observed.append,
    )
    payload = asyncio.run(tools.research("Python documentation"))
    assert payload["ok"] is True
    assert observed == [payload]
    assert observed[0]["sources"][0]["domain"] == "docs.python.org"


def test_diagnostic_projection_failures_are_nonfatal() -> None:
    hub = UIEventHub()
    hub.set_runtime_connected(True)

    def unavailable():
        raise OSError("sensitive local details")

    hub.attach_vision_provider(unavailable)
    hub.attach_health_provider(unavailable)
    snapshot = hub.snapshot()
    assert snapshot["vision"] == {"connected": False, "running": False}
    assert snapshot["health"] == []


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
        except Exception as exc:  # noqa: BLE001 - optional Chromium install
            pytest.skip(f"Chromium unavailable on this machine: {type(exc).__name__}")
        try:
            page = browser.new_page(viewport={"width": 3440, "height": 1440})
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(url, wait_until="domcontentloaded")
            page.locator("#orbCanvas").wait_for(state="visible")
            assert page.locator(".context-card").count() == 0
            assert "PREVIEW" in page.locator("#connectionBadge").inner_text()
            screenshot_dir = os.environ.get("JARVIS_UI_SCREENSHOTS")
            if screenshot_dir:
                Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(Path(screenshot_dir) / "ambient-ultrawide.png"),
                    animations="disabled",
                )
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
            page.wait_for_function(
                "() => document.querySelectorAll('.context-card').length === 0"
            )
            page.locator("#previewButton").click()
            assert "DEMO" in page.locator("#connectionBadge").inner_text()
            assert page.locator(".context-card:not(.is-closing)").count() == 2
            assert page.locator("#layout").evaluate(
                "(node) => node.classList.contains('has-stage')"
            )
            orb = page.locator("#orbCanvas").bounding_box()
            layout = page.locator("#layout").bounding_box()
            assert orb is not None and layout is not None
            orb_midpoint = orb["x"] + orb["width"] / 2
            layout_midpoint = layout["x"] + layout["width"] / 2
            assert abs(orb_midpoint - layout_midpoint) <= 12
            assert orb["width"] >= 550, "ultrawide orb must remain a focal object"
            # Projection starts as a tiny point at the orb. Wait for its
            # materialization before asserting the final responsive width.
            page.wait_for_function(
                "() => { const panel = document.querySelector('.context-card[data-slot=\"0\"]'); "
                "return panel && panel.getBoundingClientRect().width >= 700; }"
            )
            first_panel = page.locator(".context-card[data-slot='0']").bounding_box()
            assert first_panel is not None and first_panel["width"] >= 700
            assert page.locator(".context-card[data-slot='0']").count() == 1
            assert page.locator(".context-card[data-slot='1']").count() == 1
            page.wait_for_function(
                "() => document.querySelectorAll('#beamLayer .projection-link').length === 2"
            )
            assert page.locator(".holo-telemetry").count() == 1
            assert page.locator(".holo-activity").count() == 1
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / "projection-ultrawide.png"),
                    animations="disabled",
                )
                page.set_viewport_size({"width": 1920, "height": 1080})
                page.screenshot(
                    path=str(Path(screenshot_dir) / "projection-1920.png"),
                    animations="disabled",
                )
                page.set_viewport_size({"width": 3440, "height": 1440})
            assert page.evaluate(
                "() => document.querySelector('.context-card').getAnimations().length > 0"
            )
            page.locator("#orbToggle").click()
            assert page.locator("#orbToggle").get_attribute("aria-expanded") == "true"
            assert page.locator("#radialMenu").get_attribute("aria-hidden") == "false"
            page.keyboard.press("Escape")
            assert page.locator("#orbToggle").get_attribute("aria-expanded") == "false"
            page.locator("#motionButton").click()
            assert page.locator("#app").get_attribute("data-quality") == "balanced"
            page.locator("#motionButton").click()
            assert page.locator("#app").get_attribute("data-quality") == "eco"
            page.locator("#motionButton").click()
            assert page.locator("#app").get_attribute("data-quality") == "cinematic"
            page.locator("#previewButton").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.context-card').length === 0"
            )
            # A rapid off/on sequence must cancel the retracting animation,
            # never delete a panel that the owner has just reopened.
            page.locator("#previewButton").click()
            assert page.locator(".context-card:not(.is-closing)").count() == 2
            page.locator("#previewButton").click()
            page.locator("#previewButton").click()
            page.wait_for_timeout(750)
            assert page.locator(".context-card:not(.is-closing)").count() == 2
            assert page.locator(".context-card.is-closing").count() == 0
            page.locator("#previewButton").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.context-card').length === 0"
            )
            assert not errors, errors
            # On reduced-motion systems the globe remains visible but stops
            # continuous animation.
            page.emulate_media(reduced_motion="reduce")
            assert page.locator("#orbCanvas").is_visible()
            page.locator("#previewButton").click()
            assert page.locator(".context-card:not(.is-closing)").count() == 2
            assert page.locator(".context-card").first.evaluate(
                "(node) => node.getAnimations().length === 0"
            )
        finally:
            browser.close()



def test_live_runtime_research_and_diagnostics_browser_projection(ui_http) -> None:
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    hub, url = ui_http
    hub.set_runtime_connected(True)
    hub.set_voice_state("speaking")
    hub.attach_work_provider(
        lambda: [{"id": "work-123", "kind": "research", "state": "running"}]
    )
    hub.attach_vision_provider(
        lambda: {
            "running": True,
            "active_source": "lenovo",
            "available_sources": ["lenovo", "pocket3"],
        }
    )
    hub.attach_health_provider(
        lambda: [{"component": "runtime.voice", "state": "healthy"}]
    )
    hub.show_research_result(
        {
            "ok": True,
            "query": "HIDDEN PRIVATE QUERY",
            "sources": [
                {
                    "title": "Official source",
                    "url": "https://docs.python.org/3/reference/?secret=HIDDEN",
                }
            ],
        }
    )
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - optional browser
            pytest.skip(f"Chromium unavailable: {type(exc).__name__}")
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.querySelector('.live-source') !== null"
            )
            assert "RUNTIME LINKED" in page.locator("#connectionBadge").inner_text()
            assert "Speaking" in page.locator("#voiceState").inner_text()
            assert page.locator(".live-source").count() == 1
            assert page.locator(".live-source").first.get_attribute("href") == (
                "https://docs.python.org/3/reference/"
            )
            assert "HIDDEN" not in page.locator("#cards").inner_text()
            page.locator(".rail-button[data-panel='vision']").click()
            assert "LENOVO" in page.locator("#cards").inner_text()
            page.locator(".rail-button[data-panel='system']").click()
            assert "RUNTIME.VOICE" in page.locator("#cards").inner_text().upper()
            page.locator(".rail-button[data-panel='work']").click()
            assert "work-123" in page.locator("#cards").inner_text()
            assert not errors, errors
        finally:
            browser.close()


def test_ui_responsive_keyboard_and_projection_geometry(ui_http) -> None:
    """UI-only acceptance over laptop and phone viewports, with no runtime actions."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    _, url = ui_http
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - optional browser
            pytest.skip(f"Chromium unavailable on this machine: {type(exc).__name__}")
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(url, wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            assert page.locator("#visualCommand").evaluate(
                "(node) => document.activeElement === node"
            )
            page.locator("#visualCommand").fill("Jarvis, show me research")
            page.keyboard.press("Enter")
            assert page.locator(".context-card:not(.is-closing)").count() == 1
            page.wait_for_function(
                "() => document.querySelectorAll('#beamLayer .projection-link').length === 1"
            )
            assert page.evaluate(
                "() => document.documentElement.scrollWidth <= innerWidth + 2"
            )
            page.locator("#orbToggle").click()
            assert page.locator("#orbToggle").get_attribute("aria-expanded") == "true"
            page.locator("[data-orb-panel='work']").click()
            assert page.locator("#orbToggle").get_attribute("aria-expanded") == "false"
            assert page.locator(".context-card:not(.is-closing)").count() == 2

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "() => document.querySelector('#orbCanvas').getBoundingClientRect().width > 50"
            )
            assert page.evaluate(
                "() => document.documentElement.scrollWidth <= innerWidth + 2"
            ), "mobile UI should never scroll horizontally"
            assert page.locator(".context-card:not(.is-closing)").count() == 2
            for selector in (
                "#orbCanvas",
                "#visualCommand",
                ".rail",
                ".rail-button[data-action=home]",
            ):
                assert page.locator(selector).is_visible()
            assert page.locator("#projectionLinks").evaluate(
                "(node) => getComputedStyle(node).display === 'none'"
            ), "mobile stacks panel cards instead of drawing overlapping beams"
            screenshot_dir = os.environ.get("JARVIS_UI_SCREENSHOTS")
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / "projection-mobile.png"),
                    full_page=True,
                    animations="disabled",
                )
            page.locator(".rail-button[data-action=home]").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.context-card').length === 0"
            )
            assert not errors, errors
        finally:
            browser.close()
