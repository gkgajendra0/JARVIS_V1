from __future__ import annotations

import types
from pathlib import Path

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.local_reads import (
    ApprovedRootPolicy,
    LocalProjectReadExecutor,
    LocalReadValidationError,
)
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityStatus,
)
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.system_reads import SystemReadExecutor


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
        self.events.append(f"audit:{result.status.value}")

    def close(self) -> None:
        self.events.append("close")


def build_runtime(*executors):
    builtins = tuple(executor.descriptor for executor in executors)
    authority = FakeAuthority()
    runtime = CapabilityRuntime(
        executors=tuple(executors),
        resolver=CapabilityResolver((), builtins=builtins),
        authority=authority,
    )
    return runtime, authority


def test_runtime_authorizes_consumes_then_executes_and_audits(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    executor = LocalProjectReadExecutor(ApprovedRootPolicy(project_root=tmp_path))
    runtime, authority = build_runtime(executor)

    result = runtime.execute_operation(
        session_id="session-1",
        operation="read_file",
        parameters={"root": "project", "path": "note.txt"},
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["text"] == "hello"
    assert authority.events == ["authorize:read_file", "consume", "audit:succeeded"]


def test_runtime_refuses_discovery_only_capability() -> None:
    discovered = CapabilityDescriptor.create(
        capability_id="desktop.ui",
        source_id="windows.winapp",
        kind=CapabilityKind.STRUCTURED_AUTOMATION,
        name="winapp",
        description="discovery only",
        operations=["click"],
        execution_enabled=False,
    )
    runtime = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=(discovered,)),
        authority=FakeAuthority(),
    )

    result = runtime.execute(
        CapabilityRequest(
            session_id="session-1",
            capability_key=discovered.key,
            operation="click",
            parameters={},
        )
    )

    assert result.status is CapabilityStatus.DENIED
    assert "execution-disabled" in (result.reason or "")


def test_approved_root_blocks_parent_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    policy = ApprovedRootPolicy(project_root=root)

    with pytest.raises(LocalReadValidationError, match="parent path traversal"):
        policy.resolve("project", "../outside/secret.txt")

    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this test host")
    with pytest.raises(LocalReadValidationError, match="escapes approved root"):
        policy.resolve("project", "escape/secret.txt")


def test_sensitive_paths_are_blocked_before_execution(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=example", encoding="utf-8")
    executor = LocalProjectReadExecutor(ApprovedRootPolicy(project_root=tmp_path))
    request = CapabilityRequest(
        session_id="session-1",
        capability_key=executor.capability_key,
        operation="read_file",
        parameters={"root": "project", "path": ".env"},
    )

    with pytest.raises(LocalReadValidationError, match="sensitive"):
        executor.prepare(request)


def test_secret_like_content_is_never_released(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text(
        "token sk-abcdefghijklmnopqrstuvwxyz123456",
        encoding="utf-8",
    )
    executor = LocalProjectReadExecutor(ApprovedRootPolicy(project_root=tmp_path))
    runtime, _ = build_runtime(executor)

    result = runtime.execute_operation(
        session_id="session-1",
        operation="read_file",
        parameters={"root": "project", "path": "note.txt"},
    )

    assert result.status is CapabilityStatus.INVALID
    assert result.data == {}
    assert "secret-like" in (result.reason or "")


def test_document_conversion_uses_local_markitdown_and_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "report.pdf"
    document.write_bytes(b"fake-pdf")
    called: list[str] = []

    class FakeConverter:
        def convert_local(self, path: str):
            called.append(path)
            return types.SimpleNamespace(text_content="safe converted document")

    fake_module = types.SimpleNamespace(MarkItDown=FakeConverter)
    monkeypatch.setattr(
        "jarvis.capabilities.local_reads.importlib.import_module",
        lambda name: fake_module if name == "markitdown" else None,
    )
    executor = LocalProjectReadExecutor(ApprovedRootPolicy(project_root=tmp_path))
    runtime, _ = build_runtime(executor)

    result = runtime.execute_operation(
        session_id="session-1",
        operation="read_document",
        parameters={"root": "project", "path": "report.pdf"},
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["text"] == "safe converted document"
    assert called == [str(document.resolve())]
    assert result.provenance == ("Microsoft MarkItDown",)


def test_system_status_is_routine_and_process_list_is_private() -> None:
    executor = SystemReadExecutor()
    status = executor.prepare(
        CapabilityRequest(
            session_id="session-1",
            capability_key=executor.capability_key,
            operation="system_status",
            parameters={},
        )
    )
    processes = executor.prepare(
        CapabilityRequest(
            session_id="session-1",
            capability_key=executor.capability_key,
            operation="list_processes",
            parameters={"max_results": 5},
        )
    )

    assert status.attributes == ActionAttributes()
    assert processes.attributes.private_read is True


def test_system_status_executes_through_generic_runtime() -> None:
    runtime, authority = build_runtime(SystemReadExecutor())

    result = runtime.execute_operation(
        session_id="session-1",
        operation="system_status",
        parameters={},
    )

    assert result.ok
    assert result.data["memory_total_bytes"] > 0
    assert result.data["cpu_logical_count"] >= 1
    assert authority.events[:2] == ["authorize:system_status", "consume"]
