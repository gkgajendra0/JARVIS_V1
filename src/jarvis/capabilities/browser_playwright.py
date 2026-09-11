"""Structured browser execution for JARVIS Hands H3 using Playwright."""

from __future__ import annotations

import pathlib
import re
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlparse

from jarvis.authority.types import ActionAttributes, ActionScope
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.local_writes import ApprovedWriteRootPolicy, _contains_secret
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

_MAX_STEPS = 12
_MAX_TEXT = 10_000
_MAX_URL = 2_048
_BLOCKED_CLICK_TERMS = (
    "buy",
    "purchase",
    "checkout",
    "place order",
    "pay",
    "send",
    "submit",
    "delete",
    "remove",
    "unsubscribe",
    "install",
    "uninstall",
    "confirm order",
    "transfer",
)


class BrowserValidationError(ValueError):
    pass


def _validate_url(value: object) -> str:
    url = str(value or "").strip()
    if not url or len(url) > _MAX_URL:
        raise BrowserValidationError(
            "browser URL is empty or exceeds the bounded limit"
        )
    parsed = urlparse(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise BrowserValidationError(
            "browser navigation allows only explicit http/https URLs"
        )
    if parsed.username or parsed.password:
        raise BrowserValidationError("credentials embedded in browser URLs are blocked")
    return url


def _selector(step: dict[str, Any]) -> dict[str, str]:
    kind = str(step.get("selector_kind") or "").strip().casefold()
    value = str(step.get("selector") or "").strip()
    if kind not in {"role", "text", "label", "placeholder", "testid"}:
        raise BrowserValidationError("browser selector kind is not supported")
    if not value or len(value) > 300:
        raise BrowserValidationError("browser selector is empty or too long")
    return {"kind": kind, "value": value}


def _dangerous_selector(value: str) -> bool:
    normalized = " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())
    return any(term in normalized for term in _BLOCKED_CLICK_TERMS)


class BrowserBackend(Protocol):
    def navigate(self, url: str) -> dict[str, Any]: ...

    def click(self, selector: dict[str, str]) -> dict[str, Any]: ...

    def fill(self, selector: dict[str, str], text: str) -> dict[str, Any]: ...

    def read_text(self, selector: dict[str, str] | None) -> dict[str, Any]: ...

    def wait_for(self, selector: dict[str, str]) -> dict[str, Any]: ...

    def download(
        self, selector: dict[str, str], destination: pathlib.Path
    ) -> dict[str, Any]: ...

    def upload(
        self, selector: dict[str, str], source: pathlib.Path
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class PlaywrightBrowserBackend:
    """Persistent browser context owned by one CapabilityRuntime session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_page(self):
        with self._lock:
            if self._page is not None:
                return self._page
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise BrowserValidationError(
                    "browser Hands requires the jarvis[browser-hands] extra"
                ) from exc
            self._playwright = sync_playwright().start()
            try:
                self._browser = self._playwright.chromium.launch(headless=False)
            except Exception as exc:
                self._playwright.stop()
                self._playwright = None
                raise BrowserValidationError(
                    "Playwright Chromium is not installed; run jarvis-setup after installing browser-hands"
                ) from exc
            self._context = self._browser.new_context(accept_downloads=True)
            self._page = self._context.new_page()
            return self._page

    @staticmethod
    def _locator(page, selector: dict[str, str]):
        kind, value = selector["kind"], selector["value"]
        if kind == "role":
            parts = value.split(":", 1)
            if len(parts) != 2 or not all(part.strip() for part in parts):
                raise BrowserValidationError("role selector must use role:name")
            return page.get_by_role(parts[0].strip(), name=parts[1].strip())
        if kind == "text":
            return page.get_by_text(value, exact=True)
        if kind == "label":
            return page.get_by_label(value, exact=True)
        if kind == "placeholder":
            return page.get_by_placeholder(value, exact=True)
        return page.get_by_test_id(value)

    def navigate(self, url: str) -> dict[str, Any]:
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        return {"url": page.url, "title": page.title()}

    def click(self, selector: dict[str, str]) -> dict[str, Any]:
        page = self._ensure_page()
        self._locator(page, selector).click(timeout=10_000)
        return {"url": page.url, "title": page.title()}

    def fill(self, selector: dict[str, str], text: str) -> dict[str, Any]:
        page = self._ensure_page()
        locator = self._locator(page, selector)
        locator.fill(text, timeout=10_000)
        actual = locator.input_value(timeout=5_000)
        if actual != text:
            raise BrowserValidationError("browser fill verification failed")
        return {"value": actual, "url": page.url}

    def read_text(self, selector: dict[str, str] | None) -> dict[str, Any]:
        page = self._ensure_page()
        text = (
            self._locator(page, selector).inner_text(timeout=10_000)
            if selector is not None
            else page.locator("body").inner_text(timeout=10_000)
        )
        return {"text": text[:40_000], "truncated": len(text) > 40_000, "url": page.url}

    def wait_for(self, selector: dict[str, str]) -> dict[str, Any]:
        page = self._ensure_page()
        self._locator(page, selector).wait_for(state="visible", timeout=10_000)
        return {"visible": True, "url": page.url}

    def download(
        self, selector: dict[str, str], destination: pathlib.Path
    ) -> dict[str, Any]:
        page = self._ensure_page()
        with page.expect_download(timeout=20_000) as info:
            self._locator(page, selector).click(timeout=10_000)
        download = info.value
        destination.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise BrowserValidationError("browser download verification failed")
        return {"path_exists": True, "size_bytes": destination.stat().st_size}

    def upload(self, selector: dict[str, str], source: pathlib.Path) -> dict[str, Any]:
        if not source.is_file():
            raise BrowserValidationError("browser upload source does not exist")
        page = self._ensure_page()
        self._locator(page, selector).set_input_files(str(source), timeout=10_000)
        return {"file_selected": True, "source_name": source.name}

    def close(self) -> None:
        with self._lock:
            if self._context is not None:
                self._context.close()
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()
            self._page = self._context = self._browser = self._playwright = None


class BrowserPlanExecutor:
    capability_key = "browser:playwright"
    operations = ("execute_browser_plan",)

    def __init__(
        self,
        backend: BrowserBackend | None = None,
        write_roots: ApprovedWriteRootPolicy | None = None,
    ) -> None:
        self._backend = backend or PlaywrightBrowserBackend()
        self._write_roots = write_roots
        self.descriptor = CapabilityDescriptor.create(
            capability_id="playwright",
            source_id="browser",
            kind=CapabilityKind.STRUCTURED_AUTOMATION,
            name="Playwright structured browser Hands",
            description=(
                "Bounded browser navigation, semantic locators, form filling, uploads/downloads "
                "and page reads without arbitrary JavaScript or shell execution."
            ),
            operations=list(self.operations),
            metadata={"backend": "Playwright Chromium", "arbitrary_javascript": False},
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "execute_browser_plan":
            raise BrowserValidationError("unsupported browser operation")
        raw = request.parameters.get("plan")
        if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_STEPS:
            raise BrowserValidationError("browser plan must contain 1-12 bounded steps")
        plan: list[dict[str, Any]] = []
        has_click = has_upload = has_download = False
        for item in raw:
            if not isinstance(item, dict):
                raise BrowserValidationError("browser plan steps must be objects")
            action = str(item.get("action") or "").strip().casefold()
            step: dict[str, Any] = {"action": action}
            if action == "navigate":
                step["url"] = _validate_url(item.get("url"))
            elif action in {
                "click",
                "fill",
                "read_text",
                "wait_for",
                "download",
                "upload",
            }:
                selector = _selector(item)
                if action in {"click", "download"} and _dangerous_selector(
                    selector["value"]
                ):
                    raise BrowserValidationError(
                        "high-consequence browser click is outside the generic H3 plan"
                    )
                step["selector"] = selector
                if action == "fill":
                    text = str(item.get("text") or "")
                    if not text or len(text) > _MAX_TEXT or _contains_secret(text):
                        raise BrowserValidationError(
                            "browser fill text is invalid or credential-like"
                        )
                    step["text"] = text
                elif action in {"download", "upload"}:
                    if self._write_roots is None:
                        raise BrowserValidationError(
                            "browser file transfer needs approved user file roots"
                        )
                    root = str(item.get("root") or "").strip().casefold()
                    path = str(item.get("path") or "").strip()
                    _, target, relative = self._write_roots.resolve(root, path)
                    if action == "upload" and not target.is_file():
                        raise BrowserValidationError("upload source does not exist")
                    step.update(
                        root=root, path=relative.as_posix(), resolved_path=str(target)
                    )
                    has_upload |= action == "upload"
                    has_download |= action == "download"
                has_click |= action == "click"
            elif action == "read_page":
                pass
            else:
                raise BrowserValidationError("unsupported browser plan action")
            plan.append(step)

        attributes = ActionAttributes(
            private_read=True,
            reversible_local_change=any(
                step["action"] in {"navigate", "fill", "wait_for"} for step in plan
            ),
            persistent_write=has_download,
            external_side_effect=has_click or has_upload,
            scope=ActionScope.LIMITED if len(plan) > 1 else ActionScope.SINGLE,
        )
        return PreparedCapability(
            request=request,
            target={"domain": "browser.navigation_execution", "steps": len(plan)},
            parameters={
                "plan": [
                    {k: v for k, v in step.items() if k != "resolved_path"}
                    for step in plan
                ]
            },
            material_summary=f"Execute bounded Playwright browser plan with {len(plan)} step(s)",
            attributes=attributes,
            execution_payload={"plan": plan},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        results: list[dict[str, Any]] = []
        try:
            for step in prepared.execution_payload["plan"]:
                action = step["action"]
                if action == "navigate":
                    data = self._backend.navigate(step["url"])
                elif action == "click":
                    data = self._backend.click(step["selector"])
                elif action == "fill":
                    data = self._backend.fill(step["selector"], step["text"])
                elif action == "read_text":
                    data = self._backend.read_text(step["selector"])
                elif action == "read_page":
                    data = self._backend.read_text(None)
                elif action == "wait_for":
                    data = self._backend.wait_for(step["selector"])
                elif action == "download":
                    data = self._backend.download(
                        step["selector"], pathlib.Path(step["resolved_path"])
                    )
                elif action == "upload":
                    data = self._backend.upload(
                        step["selector"], pathlib.Path(step["resolved_path"])
                    )
                else:
                    raise BrowserValidationError("unsupported prepared browser action")
                results.append({"action": action, "data": data})
        except Exception as exc:  # noqa: BLE001 - executor boundary contains backend faults
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={"steps_completed": len(results), "results": results},
                reason=str(exc),
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                provenance=("Playwright structured browser automation",),
            )
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={
                "steps_completed": len(results),
                "results": results,
                "verification_passed": True,
                "content_is_untrusted_data": True,
            },
            elapsed_ms=(time.monotonic() - started) * 1000.0,
            provenance=("Playwright structured browser automation",),
        )

    def close(self) -> None:
        self._backend.close()
