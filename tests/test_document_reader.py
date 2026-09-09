from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jarvis.capabilities.document_reader import (
    DocumentReaderError,
    MarkItDownSidecar,
    _sanitized_environment,
)


def test_sidecar_fails_closed_when_isolated_python_is_missing(tmp_path: Path) -> None:
    reader = MarkItDownSidecar(tmp_path / "missing-python.exe")

    with pytest.raises(DocumentReaderError, match="not installed"):
        reader.convert_local(tmp_path / "report.pdf")


def test_sidecar_uses_bounded_isolated_process_without_shell(tmp_path: Path) -> None:
    python_path = tmp_path / "python.exe"
    python_path.write_bytes(b"placeholder")
    target = tmp_path / "report.pdf"
    target.write_bytes(b"pdf")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"text": "converted", "truncated": False}),
            stderr="",
        )

    reader = MarkItDownSidecar(
        python_path,
        runner=runner,
        environment_factory=lambda: {"SYSTEMROOT": "C:/Windows"},
    )

    text, truncated = reader.convert_local(target)

    assert text == "converted"
    assert truncated is False
    command, kwargs = calls[0]
    assert command[0] == str(python_path)
    assert command[1:3] == ["-I", "-c"]
    assert command[-2:] == [str(target), "40000"]
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert kwargs["env"] == {"SYSTEMROOT": "C:/Windows"}


def test_sidecar_rejects_malformed_output(tmp_path: Path) -> None:
    python_path = tmp_path / "python.exe"
    python_path.write_bytes(b"placeholder")

    def runner(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(command, 0, stdout="not-json", stderr="")

    reader = MarkItDownSidecar(python_path, runner=runner)

    with pytest.raises(DocumentReaderError, match="invalid output"):
        reader.convert_local(tmp_path / "report.pdf")


def test_sanitized_environment_removes_common_secret_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("EXA_API_TOKEN", "secret")
    monkeypatch.setenv("NORMAL_SETTING", "safe")

    environment = _sanitized_environment()

    assert "OPENAI_API_KEY" not in environment
    assert "EXA_API_TOKEN" not in environment
    assert environment["NORMAL_SETTING"] == "safe"
