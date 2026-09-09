"""Structured Windows automation backed by Microsoft's winapp CLI."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence


class StructuredWindowsError(RuntimeError):
    """Raised when the structured Windows automation backend cannot complete."""


@dataclass(frozen=True, slots=True)
class StructuredCommandResult:
    """Normalized result for one bounded local automation command."""

    operation: str
    elapsed_ms: float
    payload: dict[str, Any]
    stdout: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "payload": self.payload,
            "stdout": self.stdout,
        }


class WinAppCliBackend:
    """Thin adapter around Microsoft's winapp UI Automation CLI.

    The adapter never invokes a shell. It exposes only a bounded subset of
    winapp's UIA/input commands required by the JARVIS capability runtime.
    """

    MAX_TEXT_CHARACTERS = 500
    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if platform.system() != "Windows":
            raise StructuredWindowsError("winapp automation currently requires Windows")
        resolved = executable or shutil.which("winapp")
        if not resolved:
            raise StructuredWindowsError(
                "Microsoft winapp CLI is not installed; "
                "install with: winget install Microsoft.winappcli --source winget"
            )
        self._executable = resolved
        self._runner = runner
        self._sleeper = sleeper
        self._monotonic = monotonic

    @property
    def executable(self) -> str:
        return self._executable

    def _run(
        self,
        args: Sequence[str],
        *,
        operation: str,
        timeout: float | None = None,
        expect_json: bool = False,
        check: bool = True,
    ) -> StructuredCommandResult:
        started = self._monotonic()
        try:
            completed = self._runner(
                [self._executable, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.DEFAULT_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StructuredWindowsError(
                f"winapp {operation} timed out after "
                f"{timeout or self.DEFAULT_TIMEOUT_SECONDS:.1f}s"
            ) from exc
        elapsed_ms = (self._monotonic() - started) * 1000

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        payload: dict[str, Any] = {}
        if stdout and expect_json:
            try:
                decoded = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise StructuredWindowsError(
                    f"winapp {operation} returned invalid JSON: {stdout[:300]}"
                ) from exc
            if isinstance(decoded, dict):
                payload = decoded
            else:
                payload = {"value": decoded}

        if check and completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise StructuredWindowsError(f"winapp {operation} failed: {detail[:500]}")

        payload.setdefault("exit_code", int(completed.returncode))
        return StructuredCommandResult(
            operation=operation,
            elapsed_ms=elapsed_ms,
            payload=payload,
            stdout=stdout if not expect_json else "",
        )

    def probe(self) -> StructuredCommandResult:
        return self._run(
            ["--help"],
            operation="probe",
            timeout=5.0,
            expect_json=False,
        )

    def status(
        self,
        app: str,
        *,
        check: bool = True,
    ) -> StructuredCommandResult:
        target = self._validate_target(app)
        return self._run(
            ["ui", "status", "-a", target, "--json"],
            operation="status",
            timeout=5.0,
            expect_json=True,
            check=check,
        )

    def wait_until_running(
        self,
        app: str,
        *,
        timeout_seconds: float = 6.0,
        poll_seconds: float = 0.1,
    ) -> StructuredCommandResult:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("wait timeout must be between 0 and 30 seconds")
        if not 0.05 <= poll_seconds <= 1.0:
            raise ValueError("poll interval must be between 0.05 and 1 second")

        started = self._monotonic()
        last: StructuredCommandResult | None = None
        while self._monotonic() - started < timeout_seconds:
            last = self.status(app, check=False)
            if int(last.payload.get("exit_code", 1)) == 0:
                return StructuredCommandResult(
                    operation="wait_until_running",
                    elapsed_ms=(self._monotonic() - started) * 1000,
                    payload=last.payload,
                )
            self._sleeper(poll_seconds)

        detail = last.payload if last is not None else {}
        raise StructuredWindowsError(
            f"winapp could not attach to {app!r} within {timeout_seconds:.1f}s: {detail}"
        )

    def get_value(self, app: str, selector: str) -> StructuredCommandResult:
        target = self._validate_target(app)
        element = self._validate_selector(selector)
        return self._run(
            ["ui", "get-value", element, "-a", target, "--json"],
            operation="get_value",
            timeout=5.0,
            expect_json=True,
        )

    def send_text(
        self,
        app: str,
        text: str,
        *,
        target_selector: str | None = None,
    ) -> StructuredCommandResult:
        target = self._validate_target(app)
        value = str(text)
        if not value:
            raise ValueError("text must not be empty")
        if len(value) > self.MAX_TEXT_CHARACTERS:
            raise ValueError(
                f"text exceeds structured automation limit of "
                f"{self.MAX_TEXT_CHARACTERS} characters"
            )

        args = ["ui", "send-keys", value, "--verbatim", "--via", "send-input"]
        if target_selector is not None:
            args.extend(["--target", self._validate_selector(target_selector)])
        args.extend(["-a", target, "--json"])
        return self._run(
            args,
            operation="send_text",
            timeout=8.0,
            expect_json=True,
        )

    def invoke(self, app: str, selector: str) -> StructuredCommandResult:
        target = self._validate_target(app)
        element = self._validate_selector(selector)
        return self._run(
            ["ui", "invoke", element, "-a", target, "--json"],
            operation="invoke",
            timeout=8.0,
            expect_json=True,
        )

    @staticmethod
    def _validate_target(value: str) -> str:
        target = str(value).strip()
        if not target or len(target) > 160:
            raise ValueError("app target must be a non-empty bounded string")
        return target

    @staticmethod
    def _validate_selector(value: str) -> str:
        selector = str(value).strip()
        if not selector or len(selector) > 300:
            raise ValueError("UI selector must be a non-empty bounded string")
        return selector


class AllowlistedWindowsLauncher:
    """Minimal shell-free launcher for routine app start.

    This is intentionally not a general command executor. The executable map is
    explicit and tiny so the JARVIS authority layer can reason about a stable
    capability instead of arbitrary process execution.
    """

    _COMMANDS: dict[str, tuple[str, ...]] = {
        "notepad": ("notepad.exe",),
    }

    def __init__(
        self,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if platform.system() != "Windows":
            raise StructuredWindowsError("Windows app launch currently requires Windows")
        self._popen = popen
        self._monotonic = monotonic

    def launch(self, app: str) -> StructuredCommandResult:
        key = str(app).strip().casefold()
        command = self._COMMANDS.get(key)
        if command is None:
            raise StructuredWindowsError(f"app is not allow-listed: {app}")
        started = self._monotonic()
        try:
            process = self._popen(
                list(command),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise StructuredWindowsError(f"failed to launch {app}: {exc}") from exc
        elapsed_ms = (self._monotonic() - started) * 1000
        return StructuredCommandResult(
            operation="launch",
            elapsed_ms=elapsed_ms,
            payload={
                "app": key,
                "executable": command[0],
                "pid": int(getattr(process, "pid", 0) or 0),
            },
        )
