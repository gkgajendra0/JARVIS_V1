from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Self


class LocalOpaError(RuntimeError):
    pass


def default_step3_policy_path() -> Path:
    configured = os.getenv("JARVIS_STEP3_POLICY_PATH")
    if configured:
        return Path(configured).expanduser()
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "policies" / "step3_authority.rego"


def _resolve_opa_binary() -> Path:
    configured = os.getenv("JARVIS_OPA_PATH")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        raise LocalOpaError(f"configured OPA binary does not exist: {path}")
    discovered = shutil.which("opa")
    if discovered:
        return Path(discovered)
    raise LocalOpaError(
        "OPA is required for authority policy evaluation. Install OPA or set "
        "JARVIS_OPA_PATH to the opa executable."
    )


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ManagedOpaServer:
    """Short-lived loopback OPA process owned by the current JARVIS command."""

    def __init__(
        self,
        *,
        policy_path: str | Path | None = None,
        startup_timeout_seconds: float = 5.0,
    ) -> None:
        if startup_timeout_seconds <= 0:
            raise ValueError("OPA startup timeout must be positive")
        self._policy_path = (
            Path(policy_path).expanduser()
            if policy_path is not None
            else default_step3_policy_path()
        )
        self._startup_timeout_seconds = startup_timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._port: int | None = None

    @property
    def endpoint(self) -> str:
        if self._port is None:
            raise LocalOpaError("OPA server is not running")
        return f"http://127.0.0.1:{self._port}/v1/data/jarvis/authority/decision"

    def start(self) -> Self:
        if self._process is not None:
            raise LocalOpaError("OPA server is already running")
        if not self._policy_path.is_file():
            raise LocalOpaError(f"Step 3 policy file is missing: {self._policy_path}")

        binary = _resolve_opa_binary()
        self._port = _reserve_loopback_port()
        self._process = subprocess.Popen(
            [
                str(binary),
                "run",
                "--server",
                "--addr",
                f"127.0.0.1:{self._port}",
                str(self._policy_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + self._startup_timeout_seconds
        health_url = f"http://127.0.0.1:{self._port}/health"
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.close()
                raise LocalOpaError("OPA exited before becoming healthy")
            try:
                with urllib.request.urlopen(health_url, timeout=0.25) as response:
                    if response.status == 200:
                        return self
            except (OSError, TimeoutError, urllib.error.URLError):
                time.sleep(0.05)
        self.close()
        raise LocalOpaError("OPA did not become healthy before the startup timeout")

    def close(self) -> None:
        process = self._process
        self._process = None
        self._port = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
