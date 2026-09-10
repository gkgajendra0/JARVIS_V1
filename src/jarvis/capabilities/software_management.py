"""Governed Windows software discovery and package actions through WinGet."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from typing import Any, Protocol

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

_PACKAGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,199}\Z")
_MAX_QUERY = 160
_MAX_OUTPUT = 30_000


class SoftwareManagementError(ValueError):
    pass


class SoftwareBackend(Protocol):
    def search(self, query: str) -> dict[str, Any]: ...

    def list_installed(self, query: str) -> dict[str, Any]: ...

    def install(self, package_id: str) -> dict[str, Any]: ...

    def uninstall(self, package_id: str) -> dict[str, Any]: ...

    def is_installed(self, package_id: str) -> bool: ...


class WinGetBackend:
    @staticmethod
    def _exe() -> str:
        path = shutil.which("winget")
        if not path:
            raise SoftwareManagementError(
                "Windows Package Manager (winget) is unavailable"
            )
        return path

    @classmethod
    def _run(
        cls, args: list[str], *, timeout: int = 90
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [cls._exe(), *args],
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )

    @staticmethod
    def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return {
            "returncode": result.returncode,
            "stdout": stdout[:_MAX_OUTPUT],
            "stderr": stderr[:5_000],
            "truncated": len(stdout) > _MAX_OUTPUT,
            "content_is_untrusted_data": True,
        }

    def search(self, query: str) -> dict[str, Any]:
        result = self._run(
            [
                "search",
                "--query",
                query,
                "--count",
                "20",
                "--accept-source-agreements",
                "--disable-interactivity",
            ]
        )
        return self._payload(result)

    def list_installed(self, query: str) -> dict[str, Any]:
        result = self._run(
            [
                "list",
                "--query",
                query,
                "--count",
                "20",
                "--accept-source-agreements",
                "--disable-interactivity",
            ]
        )
        return self._payload(result)

    def is_installed(self, package_id: str) -> bool:
        result = self._run(
            [
                "list",
                "--id",
                package_id,
                "--exact",
                "--accept-source-agreements",
                "--disable-interactivity",
            ]
        )
        return (
            result.returncode == 0
            and package_id.casefold() in (result.stdout or "").casefold()
        )

    def install(self, package_id: str) -> dict[str, Any]:
        result = self._run(
            [
                "install",
                "--id",
                package_id,
                "--exact",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "--disable-interactivity",
            ],
            timeout=900,
        )
        return self._payload(result)

    def uninstall(self, package_id: str) -> dict[str, Any]:
        result = self._run(
            [
                "uninstall",
                "--id",
                package_id,
                "--exact",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            timeout=900,
        )
        return self._payload(result)


class SoftwareManagementExecutor:
    capability_key = "software:winget"
    operations = (
        "install_package",
        "list_installed_software",
        "search_software",
        "uninstall_package",
    )

    def __init__(self, backend: SoftwareBackend | None = None) -> None:
        self._backend = backend or WinGetBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="management",
            source_id="software",
            kind=CapabilityKind.NATIVE_API,
            name="Windows Package Manager Hands",
            description=(
                "Search/list software and install/uninstall exact package IDs through fixed WinGet argv; "
                "arbitrary command arguments are never exposed."
            ),
            operations=list(self.operations),
            metadata={"backend": "Microsoft WinGet", "shell": False},
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        operation = request.operation
        if operation not in self.operations:
            raise SoftwareManagementError("unsupported software operation")
        params: dict[str, Any] = {}
        if operation in {"search_software", "list_installed_software"}:
            query = " ".join(str(request.parameters.get("query") or "").split())
            if not query or len(query) > _MAX_QUERY:
                raise SoftwareManagementError(
                    "software query is empty or exceeds the bounded limit"
                )
            params["query"] = query
            attributes = ActionAttributes(
                private_read=operation == "list_installed_software"
            )
            summary = f"{operation.replace('_', ' ')}: {query}"
        else:
            package_id = str(request.parameters.get("package_id") or "").strip()
            if not _PACKAGE_ID.fullmatch(package_id):
                raise SoftwareManagementError(
                    "software mutation requires one exact bounded package ID"
                )
            params["package_id"] = package_id
            attributes = ActionAttributes(
                persistent_write=True,
                executable_or_system_change=True,
            )
            summary = f"{operation.replace('_', ' ')} exact package ID: {package_id}"
        return PreparedCapability(
            request=request,
            target={"domain": "software.management", **params},
            parameters=params,
            material_summary=summary,
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        operation = prepared.request.operation
        try:
            if operation == "search_software":
                data = self._backend.search(str(prepared.execution_payload["query"]))
                verified = data.get("returncode") == 0
            elif operation == "list_installed_software":
                data = self._backend.list_installed(
                    str(prepared.execution_payload["query"])
                )
                verified = data.get("returncode") == 0
            elif operation == "install_package":
                package_id = str(prepared.execution_payload["package_id"])
                data = self._backend.install(package_id)
                verified = data.get("returncode") == 0 and self._backend.is_installed(
                    package_id
                )
            else:
                package_id = str(prepared.execution_payload["package_id"])
                data = self._backend.uninstall(package_id)
                verified = data.get(
                    "returncode"
                ) == 0 and not self._backend.is_installed(package_id)
        except (SoftwareManagementError, OSError, subprocess.SubprocessError) as exc:
            return CapabilityResult(
                status=CapabilityStatus.UNAVAILABLE,
                capability_key=self.capability_key,
                operation=operation,
                data={},
                reason=str(exc),
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                provenance=("Microsoft Windows Package Manager (WinGet)",),
            )
        data = {**data, "verification_passed": verified}
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            capability_key=self.capability_key,
            operation=operation,
            data=data,
            reason=None if verified else "WinGet post-action verification failed",
            elapsed_ms=(time.monotonic() - started) * 1000.0,
            provenance=("Microsoft Windows Package Manager (WinGet)",),
        )
