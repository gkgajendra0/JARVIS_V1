from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.computer.hands_cli import main
from jarvis.config import JarvisConfig


def test_hands_cli_persists_visual_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))

    assert main(["--enable-visual"]) == 0
    assert JarvisConfig.from_environment().visual_computer_use_enabled is True
    assert "enabled" in capsys.readouterr().out

    assert main(["--disable-visual"]) == 0
    assert JarvisConfig.from_environment().visual_computer_use_enabled is False
    assert "disabled" in capsys.readouterr().out


def test_hands_cli_show_visual_reports_persisted_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))

    assert main(["--enable-visual"]) == 0
    capsys.readouterr()

    assert main(["--show-visual"]) == 0
    output = capsys.readouterr().out
    assert "window-scoped visual desktop fallback: enabled" in output
