from __future__ import annotations

import types
from pathlib import Path

import pytest

from jarvis.authority.types import (
    ActionAttributes,
    AuthorityEffect,
    TrustTier,
)
from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.execution import PreparedCapability
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


class FakeCanonicalAuthority:
    def __init__(self) -> None:
        self.evaluations: list[tuple[object, object, str | None]] = []
        self.consumed: list[tuple[str, object, object]] = []

    def evaluate(self, *, proposal, context, approval_id=None):
        self.evaluations.append((proposal, context, approval_id))
        return types.SimpleNamespace(
            effect=AuthorityEffect.ALLOW,
            execution_permit=types.SimpleNamespace(permit_id="permit-1"),
            reason_codes=(),
        )

    def revalidate_and_consume(self, *, permit_id, proposal, context):
        self.consumed.append((permit_id, proposal, context))
        return object()


class FakeStrongApproval:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def verify_and_resolve(self, *, proposal, session_id):
        self.calls.append((proposal, session_id))
        return types.SimpleNamespace(
            granted=True,
            approval=types.SimpleNamespace(approval_id="approval-1"),
            verification=types.SimpleNamespace(reason_codes=()),
        )


class FakeDocumentReader:
    def __init__(self, text: str, *, truncated: bool = False) -> None:
        self.text = text
        self.truncated = truncated
        self.calls: list[Path] = []

    def convert_local(self, target: Path) -> tuple[str, bool]:
        self.calls.append(target)
        return self.text, self.truncated


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


def test_private_read_authority_bridge_escalates_to_strong_owner() -> None:
    request = CapabilityRequest(
        session_id="session-1",
        capability_key="local:project.read",
        operation="read_file",
        parameters={"root": "project", "path": "docs/ROADMAP.md"},
    )
    prepared = PreparedCapability(
        request=request,
        target={"root_alias": "project", "relative_path_hash": "abc"},
        parameters=dict(request.parameters),
        material_summary="Read approved project file",
        attributes=ActionAttributes(private_read=True),
        execution_payload={},
    )
    canonical = FakeCanonicalAuthority()
    strong = FakeStrongApproval()
    broker = CapabilityAuthorityBroker()
    broker._authority = canonical
    broker._strong = strong

    authorized = broker.authorize(prepared)
    broker.consume(authorized)

    assert len(strong.calls) == 1
    proposal, context, approval_id = canonical.evaluations[0]
    assert proposal.attributes.private_read is True
    assert context.trust_tier is TrustTier.VERIFIED_OWNER
    assert context.actor_unambiguous is True
    assert approval_id == "approval-1"
    assert canonical.consumed[0][0] == "permit-1"
    assert canonical.consumed[0][1].fingerprint == proposal.fingerprint


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


def test_document_conversion_uses_isolated_markitdown_and_is_bounded(
    tmp_path: Path,
) -> None:
    document = tmp_path / "report.pdf"
    document.write_bytes(b"fake-pdf")
    reader = FakeDocumentReader("safe converted document")
    executor = LocalProjectReadExecutor(
        ApprovedRootPolicy(project_root=tmp_path),
        document_reader=reader,
    )
    runtime, _ = build_runtime(executor)

    result = runtime.execute_operation(
        session_id="session-1",
        operation="read_document",
        parameters={"root": "project", "path": "report.pdf"},
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["text"] == "safe converted document"
    assert reader.calls == [document.resolve()]
    assert result.provenance == ("Microsoft MarkItDown isolated sidecar",)


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
