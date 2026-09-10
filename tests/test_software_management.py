from __future__ import annotations

from typing import Any

from jarvis.capabilities.software_management import (
    SoftwareManagementExecutor,
    WinGetBackend,
)


class FakeBackend:
    def search(self, query: str) -> dict[str, Any]:
        return {"returncode": 0, "query": query}

    def list_installed(self, query: str) -> dict[str, Any]:
        return {"returncode": 0, "query": query}

    def install(self, package_id: str) -> dict[str, Any]:
        return {"returncode": 0, "package_id": package_id}

    def uninstall(self, package_id: str) -> dict[str, Any]:
        return {"returncode": 0, "package_id": package_id}

    def is_installed(self, package_id: str) -> bool:
        del package_id
        return True


def test_default_software_descriptor_reflects_winget_availability(monkeypatch) -> None:
    monkeypatch.setattr(WinGetBackend, "available", staticmethod(lambda: False))

    executor = SoftwareManagementExecutor()

    assert executor.descriptor.execution_enabled is False
    assert executor.descriptor.metadata()["available"] is False


def test_injected_software_backend_is_execution_enabled() -> None:
    executor = SoftwareManagementExecutor(FakeBackend())

    assert executor.descriptor.execution_enabled is True
    assert executor.descriptor.metadata()["available"] is True
