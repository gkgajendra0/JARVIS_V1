from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.setup import _ensure_playwright_chromium


def test_playwright_provisioning_skips_when_extra_is_absent() -> None:
    calls: list[tuple[str, ...]] = []

    ready = _ensure_playwright_chromium(
        package_available=lambda: False,
        browser_probe=lambda: pytest.fail("browser probe should not run"),
        command_runner=calls.append,
    )

    assert ready is False
    assert calls == []


def test_playwright_provisioning_reuses_launchable_chromium() -> None:
    calls: list[tuple[str, ...]] = []

    ready = _ensure_playwright_chromium(
        package_available=lambda: True,
        browser_probe=lambda: Path("C:/playwright/chrome.exe"),
        command_runner=calls.append,
    )

    assert ready is True
    assert calls == []


def test_playwright_provisioning_installs_only_fixed_chromium_payload() -> None:
    probes = iter((None, Path("C:/playwright/chrome.exe")))
    calls: list[tuple[str, ...]] = []

    ready = _ensure_playwright_chromium(
        package_available=lambda: True,
        browser_probe=lambda: next(probes),
        command_runner=calls.append,
    )

    assert ready is True
    assert calls == [
        (sys.executable, "-m", "playwright", "install", "chromium"),
    ]


def test_playwright_provisioning_surfaces_install_failure() -> None:
    def fail_install(command: tuple[str, ...]) -> None:
        raise subprocess.CalledProcessError(1, command)

    with pytest.raises(RuntimeError, match="Chromium installation failed"):
        _ensure_playwright_chromium(
            package_available=lambda: True,
            browser_probe=lambda: None,
            command_runner=fail_install,
        )


def test_playwright_provisioning_requires_post_install_launch_probe() -> None:
    calls: list[tuple[str, ...]] = []

    with pytest.raises(RuntimeError, match="still not launchable"):
        _ensure_playwright_chromium(
            package_available=lambda: True,
            browser_probe=lambda: None,
            command_runner=calls.append,
        )

    assert calls == [
        (sys.executable, "-m", "playwright", "install", "chromium"),
    ]
