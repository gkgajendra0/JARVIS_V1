from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
    ExternalAcceptanceCoordinator,
    ExternalAcceptanceError,
    ExternalAcceptanceInvokeExecutor,
    _require_activation_authority,
    external_acceptance_completion_guard,
)
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.store import ChangeStore
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


def _acceptance_recovery_state(tmp_path: Path):
    store = SQLiteWorkStore(tmp_path / "acceptance-recovery.sqlite3")
    changes = ChangeStore(
        store,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = changes.create(
        request="Acquire media control.",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    development = store.create(
        WorkItem(
            request="Build media control.",
            work_type=WorkType.DEVELOPMENT,
            source_session_id=f"change:{change.change_id}",
            source_turn_id="development:1",
            state=WorkState.COMPLETED,
        )
    )
    goal = OwnerCapabilityGoalV1.create(
        request="Play a movie on the television.",
        requested_capability="media_player.control",
        required_operations=("play_media",),
        target_hints=("Hisense U7N",),
        source_session_id="owner-session",
        source_turn_id="owner-turn",
        now_epoch=1.0,
    )
    changes.add_artifact(
        change.change_id,
        kind="capability_goal",
        payload={
            "schema": "owner_capability_goal.v1",
            "goal_id": goal.goal_id,
            **goal.canonical_payload(),
            "digest": goal.digest,
        },
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "requested_operations": ["play_media"],
            "owner_acceptance_contract_ids": [
                "phase9.real_external_effect.v1",
            ],
        },
    )
    changes.add_artifact(
        change.change_id,
        kind="substrate_manifest",
        payload={
            "manifest_id": "manifest-recovery",
            "manifest_digest": "a" * 64,
        },
    )
    candidate = changes.add_artifact(
        change.change_id,
        kind="capability_candidate",
        payload={
            "development_work_id": development.work_id,
            "capability_id": "media_player_control",
            "package_id": "media.player.control",
            "package_version": "1.0.0",
            "package_digest": "b" * 64,
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_artifact_digest": architecture.digest,
        },
    )
    activation = changes.add_artifact(
        change.change_id,
        kind="capability_lifecycle_activation",
        payload={
            "schema": "capability_acquisition_activation.v1",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "effective_enabled": True,
            "authority_session_id": "owner-session",
            "source_turn_id": "activation-turn",
        },
    )
    return store, changes, change, candidate, activation, development


def test_external_acceptance_start_repairs_crash_window_missing_binding(
    tmp_path: Path,
) -> None:
    store, changes, change, _candidate, activation, development = (
        _acceptance_recovery_state(tmp_path)
    )
    existing = store.create(
        WorkItem(
            request="Recover external acceptance after crash.",
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id=f"phase9-external:{change.change_id}",
            source_turn_id=activation.artifact_id,
            dependencies=(development.work_id,),
        )
    )
    coordinator = ExternalAcceptanceCoordinator(changes, FakeBackend())

    recovered = coordinator.start(
        change.change_id,
        activation_artifact_id=activation.artifact_id,
        authority_session_id="owner-session",
        source_turn_id="activation-turn",
    )

    assert recovered.work_id == existing.work_id
    bindings = changes.list_artifacts(
        change.change_id,
        kind=EXTERNAL_ACCEPTANCE_BINDING_KIND,
    )
    assert len(bindings) == 1
    assert bindings[0].payload["work_id"] == existing.work_id
    assert bindings[0].payload["activation_artifact_id"] == activation.artifact_id
    assert bindings[0].payload["activation_artifact_digest"] == activation.digest


def test_external_acceptance_startup_reconciliation_creates_missing_mission(
    tmp_path: Path,
) -> None:
    store, changes, change, _candidate, activation, development = (
        _acceptance_recovery_state(tmp_path)
    )
    coordinator = ExternalAcceptanceCoordinator(changes, FakeBackend())

    recovered = coordinator.reconcile_current_activations()

    assert len(recovered) == 1
    item = store.require(recovered[0])
    assert item.work_type is WorkType.EXTERNAL_ACCEPTANCE
    assert item.source_session_id == f"phase9-external:{change.change_id}"
    assert item.source_turn_id == activation.artifact_id
    assert item.dependencies == (development.work_id,)
    binding = changes.latest_artifact(
        change.change_id,
        EXTERNAL_ACCEPTANCE_BINDING_KIND,
    )
    assert binding is not None
    assert binding.payload["work_id"] == item.work_id


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


def test_external_acceptance_authority_must_match_activation_artifact() -> None:
    activation = SimpleNamespace(
        payload={
            "authority_session_id": "owner-session",
            "source_turn_id": "owner-turn",
        }
    )

    assert _require_activation_authority(
        activation,
        authority_session_id="owner-session",
        source_turn_id="owner-turn",
    ) == ("owner-session", "owner-turn")

    with pytest.raises(
        ExternalAcceptanceError,
        match="does not match the exact activation artifact",
    ):
        _require_activation_authority(
            activation,
            authority_session_id="different-session",
            source_turn_id="owner-turn",
        )


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
