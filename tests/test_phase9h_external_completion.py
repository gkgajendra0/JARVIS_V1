from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.external_acceptance import (
    ExternalAcceptanceInvokeExecutor,
    external_acceptance_completion_guard,
)
from jarvis.work.engine import (
    WorkActionRegistry,
    WorkEngine,
    WorkOwnerInputRequired,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.privacy import build_protected_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


class FakeKeyProtector:
    protector_id = "phase9h-test-protector"

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        return purpose.encode("utf-8") + b"|" + plaintext

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        prefix = purpose.encode("utf-8") + b"|"
        assert sealed.startswith(prefix)
        return sealed[len(prefix) :]


def _raw_storage(path: Path) -> bytes:
    chunks = []
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            chunks.append(candidate.read_bytes())
    return b"".join(chunks)


class FakeBackend:
    def submit(self, work_id, *, priority):
        del priority
        return work_id

    def cancel(self, execution_id, *, idempotency_key=None):
        del execution_id, idempotency_key

    def pause(self, execution_id):
        del execution_id

    def resume(self, execution_id, *, idempotency_key=None):
        del execution_id, idempotency_key


def _completed_step(
    work_id: str, kind: str, observation: dict[str, object]
) -> WorkStep:
    step = WorkStep(work_id=work_id, kind=kind, summary=kind)
    return step.start().complete(observation)


def test_sensitive_owner_input_is_redacted_and_consumed_once(tmp_path) -> None:
    path = tmp_path / "work.sqlite3"
    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"p" * size,
    )
    store = SQLiteWorkStore(path, payload_codec=codec)
    item = WorkItem(
        request="validate a real external capability",
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-demo",
        source_turn_id="activation-demo",
    )
    store.create(item)
    running = store.save(
        item.transition(WorkState.RUNNING, status_detail="invoking"),
        expected_version=item.version,
    )

    waiting_step = WorkStep(
        work_id=item.work_id,
        kind="external_acceptance_invoke",
        summary="pairing requires owner PIN",
    )
    store.add_step(waiting_step)
    store.save_step(
        waiting_step.start().complete(
            {
                "needs_owner": True,
                "question": "Enter the pairing PIN.",
                "sensitive": True,
                "input_key": "pairing_pin",
                "resume_context": {
                    "kind": "pin",
                    "parameter": "pin",
                    "request_id": "request-demo",
                },
            }
        )
    )
    waiting = store.save(
        running.transition(
            WorkState.WAITING_FOR_OWNER,
            status_detail="Enter the pairing PIN.",
            current_step_id=waiting_step.step_id,
        ),
        expected_version=running.version,
    )

    engine = WorkEngine(
        store=store,
        brain=None,  # type: ignore[arg-type]
        actions=WorkActionRegistry(()),
    )
    secret = "PAIRING_SECRET_8VJ2Q9"
    resumed = engine.apply_owner_input(waiting.work_id, secret)

    assert resumed.state is WorkState.RUNNING
    owner_step = store.list_steps(item.work_id)[-1]
    assert owner_step.kind == "owner_input"
    assert owner_step.observation["response_redacted"] is True
    assert owner_step.observation["input_key"] == "pairing_pin"
    assert "response" not in owner_step.observation
    assert secret.encode("utf-8") not in _raw_storage(path)
    assert store.pop_sensitive_input(item.work_id, "pairing_pin") == secret
    assert store.pop_sensitive_input(item.work_id, "pairing_pin") is None


def test_sensitive_owner_input_is_cleared_on_failure(tmp_path) -> None:
    path = tmp_path / "failure.sqlite3"
    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"f" * size,
    )
    store = SQLiteWorkStore(path, payload_codec=codec)
    item = WorkItem(
        request="external acceptance failure cleanup",
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-failure",
        source_turn_id="activation-failure",
    )
    store.create(item)
    running = store.save(
        item.transition(WorkState.RUNNING, status_detail="running"),
        expected_version=item.version,
    )
    store.put_sensitive_input(running.work_id, "pairing_pin", "FAILURE_SECRET_9H")

    engine = WorkEngine(
        store=store,
        brain=None,  # type: ignore[arg-type]
        actions=WorkActionRegistry(()),
    )
    failed = engine.fail(running.work_id, "synthetic failure")

    assert failed.state is WorkState.FAILED
    assert store.pop_sensitive_input(running.work_id, "pairing_pin") is None


def test_sensitive_owner_input_is_cleared_on_cancel(tmp_path) -> None:
    path = tmp_path / "cancel.sqlite3"
    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"c" * size,
    )
    store = SQLiteWorkStore(path, payload_codec=codec)
    item = WorkItem(
        request="external acceptance cancellation cleanup",
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-cancel",
        source_turn_id="activation-cancel",
    )
    store.create(item)
    store.put_sensitive_input(item.work_id, "pairing_pin", "CANCEL_SECRET_9H")

    orchestrator = WorkOrchestrator(store, FakeBackend())
    cancelled = orchestrator.cancel(item.work_id)

    assert cancelled.state is WorkState.CANCELLED
    assert store.pop_sensitive_input(item.work_id, "pairing_pin") is None


def test_external_acceptance_guard_keeps_owner_decline_pending() -> None:
    work_id = "work-external-decline"
    steps = (
        _completed_step(work_id, "external_acceptance_inspect", {"inspected": True}),
        _completed_step(work_id, "external_acceptance_prepare", {"prepared": True}),
        _completed_step(
            work_id,
            "external_acceptance_invoke",
            {"invoked": False, "owner_declined": True},
        ),
    )

    assert external_acceptance_completion_guard(steps) == (
        False,
        "external acceptance remains pending after owner decline",
    )


@pytest.mark.asyncio
async def test_external_acceptance_decline_waits_for_same_owner_authorization(
    tmp_path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "decline.sqlite3")
    item = store.create(
        WorkItem(
            request="validate a real external capability",
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id="phase9-external:change-demo",
            source_turn_id="activation-demo",
            state=WorkState.RUNNING,
        )
    )
    prepared = _completed_step(
        item.work_id,
        "external_acceptance_prepare",
        {
            "prepared": True,
            "request_id": "request-demo",
            "request_digest": "r" * 64,
            "operation": "play",
            "device_identity": "Hisense U7N",
        },
    )
    store.add_step(prepared)
    owner = _completed_step(
        item.work_id,
        "owner_input",
        {
            "input_key": "external_acceptance_authorize:request-demo",
            "response": "no",
        },
    )
    store.add_step(owner)

    class Resolver:
        def __init__(self):
            self.store = SimpleNamespace(work=store)

        def context_for(self, work_id):
            assert work_id == item.work_id
            return SimpleNamespace(
                binding=SimpleNamespace(
                    payload={"authority_session_id": "test-authority-session"}
                )
            )

    class Runtime:
        def __init__(self):
            self.called = False

        def execute_operation(self, **kwargs):
            self.called = True
            raise RuntimeError(f"live-call-reached: {kwargs}")

    runtime = Runtime()
    executor = ExternalAcceptanceInvokeExecutor(Resolver(), runtime)

    with pytest.raises(WorkOwnerInputRequired) as exc:
        await executor.execute(
            work=item,
            parameters={"operation": "play", "parameters": {}},
        )

    assert runtime.called is False
    assert exc.value.input_key == "external_acceptance_authorize:request-demo"
    assert exc.value.resume_context["kind"] == "live_acceptance_authorization"

    newer_owner = _completed_step(
        item.work_id,
        "owner_input",
        {
            "input_key": "external_acceptance_authorize:request-demo",
            "response": "yes",
        },
    )
    store.add_step(newer_owner)

    with pytest.raises(RuntimeError, match="live-call-reached"):
        await executor.execute(
            work=item,
            parameters={"operation": "play", "parameters": {}},
        )

    assert runtime.called is True


def test_external_acceptance_guard_requires_durable_real_world_evidence() -> None:
    work_id = "work-external-pass"
    before_record = (
        _completed_step(work_id, "external_acceptance_inspect", {"inspected": True}),
        _completed_step(work_id, "external_acceptance_prepare", {"prepared": True}),
        _completed_step(work_id, "external_acceptance_invoke", {"invoked": True}),
    )

    allowed, reason = external_acceptance_completion_guard(before_record)
    assert allowed is False
    assert reason == "external acceptance requires durable real-world evidence"

    after_record = before_record + (
        _completed_step(
            work_id,
            "external_acceptance_record",
            {"acceptance_recorded": True, "verdict": "pass"},
        ),
    )
    assert external_acceptance_completion_guard(after_record) == (True, None)
