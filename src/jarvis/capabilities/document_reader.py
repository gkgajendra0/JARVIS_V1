"""Isolated Microsoft MarkItDown document-reader sidecar.

MarkItDown 0.1.x depends on Magika 0.6.x, which pins Windows ONNX Runtime
<=1.20.1. JARVIS vision intentionally uses a newer accepted ONNX Runtime.
Keep the document converter in its own managed virtual environment so those
runtime dependencies never replace JARVIS's main inference stack.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import venv
from collections.abc import Callable, Mapping, Sequence

_MARKITDOWN_SPEC = "markitdown[docx,pdf,pptx,xls,xlsx]==0.1.7"
_DEFAULT_TIMEOUT_SECONDS = 45.0
_DEFAULT_OUTPUT_CHARS = 40_000
_SIDECAR_SCRIPT = r"""
import json
import sys
from markitdown import MarkItDown

limit = int(sys.argv[2])
result = MarkItDown().convert_local(sys.argv[1])
text = str(getattr(result, "text_content", "") or getattr(result, "markdown", ""))
payload = {"text": text[:limit], "truncated": len(text) > limit}
sys.stdout.write(json.dumps(payload, ensure_ascii=False))
""".strip()


class DocumentReaderError(RuntimeError):
    """Document sidecar cannot safely complete the requested conversion."""


def default_sidecar_root() -> pathlib.Path:
    configured = os.getenv("JARVIS_MARKITDOWN_SIDECAR_ROOT")
    if configured and configured.strip():
        return pathlib.Path(configured.strip()).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data and local_app_data.strip():
        return pathlib.Path(local_app_data) / "JARVIS" / "tools" / "markitdown"
    return pathlib.Path.home() / ".jarvis" / "tools" / "markitdown"


def sidecar_python_path(root: pathlib.Path | None = None) -> pathlib.Path:
    configured = os.getenv("JARVIS_MARKITDOWN_PYTHON")
    if configured and configured.strip():
        return pathlib.Path(configured.strip()).expanduser()
    base = root or default_sidecar_root()
    if os.name == "nt":
        return base / "venv" / "Scripts" / "python.exe"
    return base / "venv" / "bin" / "python"


def _sanitized_environment() -> dict[str, str]:
    blocked_tokens = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    return {
        name: value
        for name, value in os.environ.items()
        if not any(token in name.upper() for token in blocked_tokens)
    }


class MarkItDownSidecar:
    """Run MarkItDown in an isolated interpreter with bounded JSON output."""

    def __init__(
        self,
        python_path: str | pathlib.Path | None = None,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        output_chars: int = _DEFAULT_OUTPUT_CHARS,
        environment_factory: Callable[[], Mapping[str, str]] = _sanitized_environment,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("document-reader timeout must be positive")
        if output_chars < 1 or output_chars > 200_000:
            raise ValueError("document-reader output limit is invalid")
        self._python_path = pathlib.Path(python_path) if python_path else sidecar_python_path()
        self._runner = runner
        self._timeout_seconds = timeout_seconds
        self._output_chars = output_chars
        self._environment_factory = environment_factory

    @property
    def python_path(self) -> pathlib.Path:
        return self._python_path

    def convert_local(self, target: pathlib.Path) -> tuple[str, bool]:
        if not self._python_path.is_file():
            raise DocumentReaderError(
                "isolated MarkItDown reader is not installed; run "
                "jarvis-setup-document-reader"
            )
        try:
            completed = self._runner(
                [
                    str(self._python_path),
                    "-I",
                    "-c",
                    _SIDECAR_SCRIPT,
                    str(target),
                    str(self._output_chars),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
                shell=False,
                env=dict(self._environment_factory()),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentReaderError("document conversion timed out") from exc
        except OSError as exc:
            raise DocumentReaderError("document sidecar could not start") from exc
        if completed.returncode != 0:
            raise DocumentReaderError("document conversion failed")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DocumentReaderError("document sidecar returned invalid output") from exc
        if not isinstance(payload, dict):
            raise DocumentReaderError("document sidecar returned invalid output")
        text = payload.get("text")
        truncated = payload.get("truncated")
        if not isinstance(text, str) or not isinstance(truncated, bool):
            raise DocumentReaderError("document sidecar returned invalid output")
        return text, truncated


def install_sidecar(
    *,
    root: pathlib.Path | None = None,
    installer_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> pathlib.Path:
    """Explicitly provision the isolated document-reader environment."""

    target_root = (root or default_sidecar_root()).expanduser()
    environment_dir = target_root / "venv"
    python_path = sidecar_python_path(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    if not python_path.is_file():
        venv.EnvBuilder(with_pip=True, clear=False).create(environment_dir)
    try:
        completed = installer_runner(
            [
                str(python_path),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                _MARKITDOWN_SPEC,
            ],
            check=False,
            shell=False,
        )
    except OSError as exc:
        raise DocumentReaderError("document-reader dependency installation failed") from exc
    if completed.returncode != 0:
        raise DocumentReaderError("document-reader dependency installation failed")
    return python_path


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        python_path = install_sidecar()
        reader = MarkItDownSidecar(python_path)
        probe = subprocess.run(
            [
                str(reader.python_path),
                "-I",
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('markitdown'))",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20.0,
            check=False,
            shell=False,
            env=_sanitized_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if probe.returncode != 0:
            raise DocumentReaderError("document-reader validation failed")
    except (DocumentReaderError, OSError) as exc:
        print(f"JARVIS document-reader setup failed: {exc}")
        return 2
    print("JARVIS isolated document reader is ready.")
    print(f"Python: {python_path}")
    print(f"MarkItDown: {probe.stdout.strip()}")
    print("JARVIS main ONNX Runtime was not modified by this setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
