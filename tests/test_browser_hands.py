from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.authority.risk import RiskClassifier
from jarvis.authority.types import RiskClass
from jarvis.capabilities.browser_playwright import BrowserPlanExecutor, BrowserValidationError
from jarvis.capabilities.local_writes import ApprovedWriteRootPolicy
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus


class FakeBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def navigate(self, url: str):
        self.calls.append(("navigate", url))
        return {"url": url, "title": "Example"}

    def click(self, selector):
        self.calls.append(("click", selector))
        return {"url": "https://example.com/next", "title": "Next"}

    def fill(self, selector, text: str):
        self.calls.append(("fill", selector, text))
        return {"value": text, "url": "https://example.com"}

    def read_text(self, selector):
        self.calls.append(("read_text", selector))
        return {"text": "hello", "truncated": False, "url": "https://example.com"}

    def wait_for(self, selector):
        self.calls.append(("wait_for", selector))
        return {"visible": True, "url": "https://example.com"}

    def download(self, selector, destination: Path):
        self.calls.append(("download", selector, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("download")
        return {"path_exists": True, "size_bytes": 8}

    def upload(self, selector, source: Path):
        self.calls.append(("upload", selector, source))
        return {"file_selected": True, "source_name": source.name}

    def close(self) -> None:
        self.calls.append(("close",))


def roots(tmp_path: Path) -> ApprovedWriteRootPolicy:
    writable = tmp_path / "files"
    writable.mkdir()
    jarvis = tmp_path / "jarvis"
    jarvis.mkdir()
    return ApprovedWriteRootPolicy(
        roots={"files": writable},
        jarvis_root=jarvis,
        include_user_defaults=False,
    )


def request(executor: BrowserPlanExecutor, plan: list[dict]) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="browser-test",
        capability_key=executor.capability_key,
        operation="execute_browser_plan",
        parameters={"plan": plan},
    )


def test_browser_rejects_non_http_and_credential_urls() -> None:
    executor = BrowserPlanExecutor(FakeBrowser())

    with pytest.raises(BrowserValidationError, match="http/https"):
        executor.prepare(request(executor, [{"action": "navigate", "url": "file:///tmp/a"}]))
    with pytest.raises(BrowserValidationError, match="credentials"):
        executor.prepare(
            request(executor, [{"action": "navigate", "url": "https://u:p@example.com"}])
        )


def test_browser_rejects_dangerous_generic_click() -> None:
    executor = BrowserPlanExecutor(FakeBrowser())

    with pytest.raises(BrowserValidationError, match="high-consequence"):
        executor.prepare(
            request(
                executor,
                [
                    {"action": "navigate", "url": "https://example.com"},
                    {"action": "click", "selector_kind": "role", "selector": "button:Buy now"},
                ],
            )
        )


def test_browser_fill_blocks_credential_like_material() -> None:
    executor = BrowserPlanExecutor(FakeBrowser())

    with pytest.raises(BrowserValidationError, match="credential-like"):
        executor.prepare(
            request(
                executor,
                [
                    {
                        "action": "fill",
                        "selector_kind": "label",
                        "selector": "Token",
                        "text": "sk-abcdefghijklmnopqrstuvwxyz123456",
                    }
                ],
            )
        )


def test_browser_external_click_gets_persistent_external_risk() -> None:
    executor = BrowserPlanExecutor(FakeBrowser())
    prepared = executor.prepare(
        request(
            executor,
            [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "click", "selector_kind": "text", "selector": "Learn more"},
                {"action": "read_page"},
            ],
        )
    )

    assert prepared.attributes.external_side_effect is True
    assert RiskClassifier().classify(prepared.attributes).risk_class is RiskClass.PERSISTENT_OR_EXTERNAL


def test_browser_plan_executes_with_semantic_locators_and_returns_untrusted_data() -> None:
    backend = FakeBrowser()
    executor = BrowserPlanExecutor(backend)
    prepared = executor.prepare(
        request(
            executor,
            [
                {"action": "navigate", "url": "https://example.com"},
                {
                    "action": "fill",
                    "selector_kind": "label",
                    "selector": "Search",
                    "text": "BMW 310 GS",
                },
                {"action": "read_page"},
            ],
        )
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["verification_passed"] is True
    assert result.data["content_is_untrusted_data"] is True
    assert result.data["steps_completed"] == 3


def test_browser_download_is_bound_to_approved_write_root(tmp_path: Path) -> None:
    backend = FakeBrowser()
    policy = roots(tmp_path)
    executor = BrowserPlanExecutor(backend, policy)
    prepared = executor.prepare(
        request(
            executor,
            [
                {
                    "action": "download",
                    "selector_kind": "text",
                    "selector": "Download report",
                    "root": "files",
                    "path": "report.txt",
                }
            ],
        )
    )

    assert prepared.attributes.persistent_write is True
    result = executor.execute(prepared)
    assert result.status is CapabilityStatus.SUCCEEDED
    assert (policy.root("files") / "report.txt").is_file()
