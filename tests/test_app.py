from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jarvis import JarvisApp


ROOT = Path(__file__).resolve().parents[1]


def test_app_can_be_constructed() -> None:
    app = JarvisApp()

    assert app.is_running is False


def test_start_transitions_app_to_running() -> None:
    app = JarvisApp()

    app.start()

    assert app.is_running is True


def test_stop_transitions_app_to_stopped() -> None:
    app = JarvisApp()
    app.start()

    app.stop()

    assert app.is_running is False


def test_repeated_start_and_stop_preserve_valid_state() -> None:
    app = JarvisApp()

    app.stop()
    app.start()
    app.start()
    assert app.is_running is True
    app.stop()
    app.stop()
    assert app.is_running is False
    app.start()
    assert app.is_running is True


def test_package_import_has_no_network_audio_or_model_imports() -> None:
    source_root = str(ROOT / "src")
    script = """
import builtins
import sys

blocked = {"socket", "requests", "sounddevice", "pyaudio", "torch", "openai"}
original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    root = name.partition(".")[0]
    if root in blocked:
        raise AssertionError(f"unexpected external import: {root}")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import jarvis
assert jarvis.JarvisApp().is_running is False
assert blocked.isdisjoint(sys.modules)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
