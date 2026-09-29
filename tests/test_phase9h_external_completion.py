from __future__ import annotations

from pathlib import Path

from jarvis.capability_acquisition.external_acceptance import (
    external_acceptance_completion_guard,
)
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
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


def test_external_acceptance_guard_allows_explicit_owner_decline() -> None:
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

    assert external_acceptance_completion_guard(steps) == (True, None)


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
