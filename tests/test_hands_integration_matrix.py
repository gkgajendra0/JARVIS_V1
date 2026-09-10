from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.capabilities.browser_playwright import BrowserPlanExecutor
from jarvis.capabilities.development_git import (
    ApprovedRepositoryPolicy,
    DevelopmentGitExecutor,
)
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.document_edits import DocumentEditExecutor
from jarvis.capabilities.local_writes import (
    ApprovedWriteRootPolicy,
    LocalFileWriteExecutor,
)
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.software_management import SoftwareManagementExecutor
from jarvis.capabilities.windows_devices import (
    BluetoothControlExecutor,
    DisplayControlExecutor,
    PowerSessionExecutor,
)


class FakeAuthority:
    def __init__(self) -> None:
        self.events: list[str] = []

    def authorize(self, prepared):
        self.events.append(f"authorize:{prepared.request.operation}")
        return object()

    def consume(self, authorized) -> None:
        del authorized
        self.events.append("consume")

    def audit_result(self, *, session_id, authorized, result) -> None:
        del session_id, authorized
        self.events.append(f"audit:{result.operation}:{result.status.value}")

    def close(self) -> None:
        self.events.append("close")


class FakeBrowserBackend:
    def __init__(self) -> None:
        self.closed = False

    def navigate(self, url: str) -> dict[str, Any]:
        return {"url": url, "title": "Acceptance"}

    def click(self, selector: dict[str, str]) -> dict[str, Any]:
        return {"selector": selector}

    def fill(self, selector: dict[str, str], text: str) -> dict[str, Any]:
        return {"selector": selector, "value": text}

    def read_text(self, selector: dict[str, str] | None) -> dict[str, Any]:
        return {"selector": selector, "text": "safe page text"}

    def wait_for(self, selector: dict[str, str]) -> dict[str, Any]:
        return {"selector": selector, "visible": True}

    def download(self, selector: dict[str, str], destination: Path) -> dict[str, Any]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("download", encoding="utf-8")
        return {"selector": selector, "path_exists": True}

    def upload(self, selector: dict[str, str], source: Path) -> dict[str, Any]:
        return {"selector": selector, "file_selected": source.is_file()}

    def close(self) -> None:
        self.closed = True


class FakeDisplayBackend:
    def __init__(self) -> None:
        self.brightness = 50

    def list_monitors(self) -> list[dict[str, Any]]:
        return [{"name": "Test Display"}]

    def get_brightness(self, display: str | None = None) -> list[int]:
        del display
        return [self.brightness]

    def set_brightness(self, percent: int, display: str | None = None) -> list[int]:
        del display
        self.brightness = percent
        return [self.brightness]


class FakeBluetoothBackend:
    def __init__(self) -> None:
        self.paired = False

    def list_devices(self) -> list[dict[str, Any]]:
        return [{"name": "Test Buds", "is_paired": self.paired}]

    def pair(self, name: str) -> dict[str, Any]:
        self.paired = True
        return {"name": name, "is_paired": True}

    def unpair(self, name: str) -> dict[str, Any]:
        self.paired = False
        return {"name": name, "is_paired": False}


class FakePowerBackend:
    def lock(self) -> bool:
        return True

    def sleep(self) -> bool:
        return True

    def sign_out(self) -> bool:
        return True

    def restart(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


class FakeSoftwareBackend:
    def __init__(self) -> None:
        self.installed: set[str] = set()

    def search(self, query: str) -> dict[str, Any]:
        return {"returncode": 0, "query": query}

    def list_installed(self, query: str) -> dict[str, Any]:
        return {"returncode": 0, "query": query}

    def install(self, package_id: str) -> dict[str, Any]:
        self.installed.add(package_id)
        return {"returncode": 0, "package_id": package_id}

    def uninstall(self, package_id: str) -> dict[str, Any]:
        self.installed.discard(package_id)
        return {"returncode": 0, "package_id": package_id}

    def is_installed(self, package_id: str) -> bool:
        return package_id in self.installed


class FakeGitBackend:
    def __init__(self) -> None:
        self.branch = "main"
        self.created: list[str] = []

    def status(self, repo: Path) -> dict[str, Any]:
        del repo
        return {"staged": {}, "unstaged": [], "untracked": []}

    def active_branch(self, repo: Path) -> str:
        del repo
        return self.branch

    def create_branch(self, repo: Path, branch: str) -> None:
        del repo
        self.created.append(branch)
        self.branch = branch

    def stage(self, repo: Path, paths: list[str]) -> None:
        del repo, paths

    def commit(self, repo: Path, message: str) -> str:
        del repo, message
        return "abc123"

    def push_current(self, repo: Path) -> dict[str, Any]:
        del repo
        return {"branch": self.branch, "remote": "origin"}


def test_h2_h5_representative_operations_flow_through_one_runtime(
    tmp_path: Path,
) -> None:
    user_files = tmp_path / "user-files"
    user_files.mkdir()
    jarvis_source = tmp_path / "jarvis-source"
    jarvis_source.mkdir()
    write_policy = ApprovedWriteRootPolicy(
        roots={"test": user_files},
        jarvis_root=jarvis_source,
        include_user_defaults=False,
    )

    repo = tmp_path / "dev-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    repo_policy = ApprovedRepositoryPolicy(
        roots={"testrepo": repo},
        jarvis_root=jarvis_source,
        include_jarvis_read_target=False,
    )

    browser_backend = FakeBrowserBackend()
    executors = (
        LocalFileWriteExecutor(write_policy),
        DocumentEditExecutor(write_policy),
        BrowserPlanExecutor(browser_backend, write_policy),
        DisplayControlExecutor(FakeDisplayBackend()),
        BluetoothControlExecutor(FakeBluetoothBackend()),
        PowerSessionExecutor(FakePowerBackend()),
        SoftwareManagementExecutor(FakeSoftwareBackend()),
        DevelopmentGitExecutor(repo_policy, FakeGitBackend()),
    )
    authority = FakeAuthority()
    runtime = CapabilityRuntime(
        executors=executors,
        resolver=CapabilityResolver(
            (), builtins=tuple(executor.descriptor for executor in executors)
        ),
        authority=authority,
    )

    cases = (
        (
            "create_text_file",
            {"root": "test", "path": "acceptance/note.txt", "text": "hello"},
            "local:files.write",
        ),
        (
            "create_xlsx",
            {"root": "test", "path": "acceptance/data.xlsx", "sheet": "Data"},
            "local:documents.edit",
        ),
        (
            "execute_browser_plan",
            {"plan": [{"action": "navigate", "url": "https://example.com"}]},
            "browser:playwright",
        ),
        ("set_display_brightness", {"percent": 42}, "system:display"),
        ("pair_bluetooth_device", {"name": "Test Buds"}, "device:bluetooth"),
        ("lock_workstation", {}, "system:power_session"),
        (
            "install_package",
            {"package_id": "Example.SafePackage"},
            "software:winget",
        ),
        (
            "git_create_branch",
            {"repo": "testrepo", "branch": "hands-acceptance"},
            "development:git",
        ),
    )

    try:
        for operation, parameters, capability_key in cases:
            result = runtime.execute_operation(
                session_id="hands-integration-matrix",
                operation=operation,
                parameters=parameters,
            )
            assert result.ok, f"{operation}: {result.reason}"
            assert result.capability_key == capability_key
            assert result.data.get("verification_passed") is True
    finally:
        runtime.close()

    assert (user_files / "acceptance" / "note.txt").read_text(
        encoding="utf-8"
    ) == "hello"
    assert (user_files / "acceptance" / "data.xlsx").is_file()
    assert browser_backend.closed is True
    for operation, _, _ in cases:
        assert f"authorize:{operation}" in authority.events
        assert f"audit:{operation}:succeeded" in authority.events
