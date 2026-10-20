from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError

import pytest

from jarvis.work.dbos_backend import DBOSWorkExecutionBackend
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
from jarvis.work.privacy import ProtectedWorkPayloadCodec, WorkPayloadProtectionError
from jarvis.work.runtime import WorkRuntime
from jarvis.work.store import SQLiteWorkStore, WorkStoreError


def _waiting(store, *, turn="one", sensitive=True):
    item = store.create(
        WorkItem(
            request="synthetic external test",
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id="test",
            source_turn_id=turn,
        )
    )
    running = store.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    step = WorkStep(
        work_id=item.work_id, kind="external_acceptance_invoke", summary="input"
    )
    store.add_step(step)
    store.save_step(
        step.start().complete(
            {
                "needs_owner": True,
                "sensitive": sensitive,
                "input_key": "pairing_pin",
            }
        )
    )
    return store.save(
        running.transition(
            WorkState.WAITING_FOR_OWNER,
            current_step_id=step.step_id,
            status_detail="Enter fictional PIN",
        ),
        expected_version=running.version,
    )


def _runtime(store):
    runtime = object.__new__(WorkRuntime)
    runtime.store = store
    runtime.backend = DBOSWorkExecutionBackend()
    return runtime


def _capture(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "jarvis.work.dbos_backend.DBOS.send", lambda *a, **kw: messages.append((a, kw))
    )
    return messages


def _engine(store):
    return WorkEngine(store=store, brain=None, actions=WorkActionRegistry(()))


def test_sensitive_transport_survives_restart_without_plaintext_or_duplicate_input(
    tmp_path, monkeypatch
):
    path = tmp_path / "work.sqlite"
    codec = ProtectedWorkPayloadCodec(b"p" * 32)
    store = SQLiteWorkStore(path, payload_codec=codec)
    waiting = _waiting(store)
    store.set_execution_id(waiting.work_id, waiting.work_id + "__retry_v4")
    messages = _capture(monkeypatch)
    _runtime(store).submit_owner_input(waiting.work_id, "FICTIONAL_PIN_1739")
    args, kwargs = messages[0]
    message = args[1]
    assert "FICTIONAL_PIN_1739" not in json.dumps(messages)
    assert args[0] == waiting.work_id + "__retry_v4"
    assert kwargs["idempotency_key"] == f"owner-input:{waiting.version}"

    restarted = SQLiteWorkStore(path, payload_codec=codec)
    engine = _engine(restarted)
    resumed = engine.apply_owner_input(waiting.work_id, message)
    assert resumed.state is WorkState.RUNNING
    assert (
        restarted.pop_sensitive_input(waiting.work_id, "pairing_pin")
        == "FICTIONAL_PIN_1739"
    )
    assert engine.apply_owner_input(waiting.work_id, message) == resumed
    assert restarted.pop_sensitive_input(waiting.work_id, "pairing_pin") is None
    assert (
        len(
            [
                s
                for s in restarted.list_steps(waiting.work_id)
                if s.kind == "owner_input"
            ]
        )
        == 1
    )
    for file in tmp_path.iterdir():
        assert b"FICTIONAL_PIN_1739" not in file.read_bytes()


@pytest.mark.parametrize("case", ["wrong_work", "stale", "tampered", "later_wait"])
def test_sensitive_transport_rejects_invalid_binding(tmp_path, monkeypatch, case):
    store = SQLiteWorkStore(
        tmp_path / "work.sqlite", payload_codec=ProtectedWorkPayloadCodec(b"p" * 32)
    )
    waiting = _waiting(store)
    messages = _capture(monkeypatch)
    _runtime(store).submit_owner_input(waiting.work_id, "FICTIONAL_PIN_1739")
    message = messages[0][0][1]
    target = waiting
    if case == "wrong_work":
        target = _waiting(store, turn="two")
    elif case == "stale":
        store.save(
            waiting.with_progress(
                current_step_id=waiting.current_step_id, status_detail="changed"
            ),
            expected_version=waiting.version,
        )
    elif case == "tampered":
        message = message[:-7] + "invalid"
    elif case == "later_wait":
        engine = _engine(store)
        resumed = engine.apply_owner_input(waiting.work_id, message)
        store.pop_sensitive_input(waiting.work_id, "pairing_pin")
        store.save(
            resumed.transition(
                WorkState.WAITING_FOR_OWNER, current_step_id=waiting.current_step_id
            ),
            expected_version=resumed.version,
        )
    with pytest.raises((ValueError, WorkStoreError)):
        _engine(store).apply_owner_input(target.work_id, message)
    assert store.require(target.work_id).state is WorkState.WAITING_FOR_OWNER
    assert store.pop_sensitive_input(target.work_id, "pairing_pin") is None


def test_sensitive_transport_requires_payload_protection(tmp_path, monkeypatch):
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    waiting = _waiting(store)
    messages = _capture(monkeypatch)
    with pytest.raises(WorkStoreError, match="protect"):
        _runtime(store).submit_owner_input(waiting.work_id, "FICTIONAL_PIN_1739")
    assert messages == []


def test_ordinary_owner_response_keeps_existing_transport(tmp_path, monkeypatch):
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    waiting = _waiting(store, sensitive=False)
    messages = _capture(monkeypatch)
    _runtime(store).submit_owner_input(waiting.work_id, "yes")
    assert messages[0][0][1] == "yes"
    assert (
        _engine(store).apply_owner_input(waiting.work_id, "yes").state
        is WorkState.RUNNING
    )


@pytest.mark.parametrize(
    "change", ["ordinary_to_sensitive", "sensitive_to_ordinary", "progress"]
)
def test_owner_input_transport_rejects_wait_changed_after_runtime_resolution(
    tmp_path, monkeypatch, change
):
    store = SQLiteWorkStore(
        tmp_path / "work.sqlite", payload_codec=ProtectedWorkPayloadCodec(b"p" * 32)
    )
    waiting = _waiting(store, sensitive=change == "sensitive_to_ordinary")
    runtime = _runtime(store)
    messages = _capture(monkeypatch)

    def resolve_then_change(work_id):
        assert work_id == waiting.work_id
        if change == "progress":
            store.save(
                waiting.with_progress(
                    current_step_id=waiting.current_step_id, status_detail="changed"
                ),
                expected_version=waiting.version,
            )
        else:
            running = store.save(
                waiting.transition(WorkState.RUNNING), expected_version=waiting.version
            )
            step = WorkStep(
                work_id=waiting.work_id,
                kind="external_acceptance_invoke",
                summary="new wait",
            )
            store.add_step(step)
            store.save_step(
                step.start().complete(
                    {
                        "needs_owner": True,
                        "sensitive": change == "ordinary_to_sensitive",
                        "input_key": "new_input",
                    }
                )
            )
            store.save(
                running.transition(
                    WorkState.WAITING_FOR_OWNER, current_step_id=step.step_id
                ),
                expected_version=running.version,
            )
        return waiting

    monkeypatch.setattr(runtime, "resolve_waiting_owner_work", resolve_then_change)
    with pytest.raises(WorkStoreError, match="stale"):
        runtime.submit_owner_input(waiting.work_id, "FICTIONAL_PIN_1739")
    assert messages == []


def test_ordinary_wait_does_not_reuse_a_historical_sensitive_request(
    tmp_path, monkeypatch
):
    store = SQLiteWorkStore(
        tmp_path / "work.sqlite", payload_codec=ProtectedWorkPayloadCodec(b"p" * 32)
    )
    waiting = _waiting(store)
    running = store.save(
        waiting.transition(WorkState.RUNNING), expected_version=waiting.version
    )
    ordinary = store.save(
        running.transition(WorkState.WAITING_FOR_OWNER, status_detail="Continue?"),
        expected_version=running.version,
    )
    messages = _capture(monkeypatch)
    _runtime(store).submit_owner_input(ordinary.work_id, "yes")
    assert messages[0][0][1] == "yes"
    _engine(store).apply_owner_input(ordinary.work_id, messages[0][0][1])
    assert store.list_steps(ordinary.work_id)[-1].observation == {"response": "yes"}
    assert store.pop_sensitive_input(ordinary.work_id, "pairing_pin") is None


@pytest.mark.parametrize("later_wait", [False, True])
def test_legacy_raw_pin_cannot_resume_sensitive_wait_or_restore_consumed_input(
    tmp_path, later_wait
):
    store = SQLiteWorkStore(
        tmp_path / "work.sqlite", payload_codec=ProtectedWorkPayloadCodec(b"p" * 32)
    )
    waiting = _waiting(store)
    engine = _engine(store)
    secret = "FICTIONAL_LEGACY_PIN_7319"
    if later_wait:
        message = store.owner_input_transport(waiting, secret)
        resumed = engine.apply_owner_input(waiting.work_id, message)
        assert store.pop_sensitive_input(waiting.work_id, "pairing_pin") == secret
        next_step = WorkStep(
            work_id=waiting.work_id,
            kind="external_acceptance_invoke",
            summary="later pairing request",
        )
        store.add_step(next_step)
        store.save_step(
            next_step.start().complete(
                {
                    "needs_owner": True,
                    "sensitive": True,
                    "input_key": "pairing_pin",
                }
            )
        )
        waiting = store.save(
            resumed.transition(
                WorkState.WAITING_FOR_OWNER, current_step_id=next_step.step_id
            ),
            expected_version=resumed.version,
        )
    steps_before = store.list_steps(waiting.work_id)
    with pytest.raises((ValueError, WorkStoreError), match="protect"):
        engine.apply_owner_input(waiting.work_id, secret)
    assert store.require(waiting.work_id) == waiting
    assert store.list_steps(waiting.work_id) == steps_before
    assert store.pop_sensitive_input(waiting.work_id, "pairing_pin") is None


def test_separate_work_stores_consume_sensitive_input_only_once(tmp_path, monkeypatch):
    path = tmp_path / "work.sqlite"
    codec = ProtectedWorkPayloadCodec(b"p" * 32)
    first = SQLiteWorkStore(path, payload_codec=codec)
    waiting = _waiting(first)
    first.put_sensitive_input(
        waiting.work_id, "pairing_pin", "FICTIONAL_CONCURRENT_PIN_1739"
    )
    second = SQLiteWorkStore(path, payload_codec=codec)
    both_decoded = Barrier(2)

    def coordinate_decoder(store):
        decode = store._decode_text

        def decode_at_same_time(value):
            decoded = decode(value)
            try:
                # Before the fix, both readers reach this barrier before DELETE.
                # With serialization, the second reader waits at BEGIN IMMEDIATE,
                # so the first must be allowed to finish without a second decoder.
                both_decoded.wait(timeout=1.0)
            except BrokenBarrierError:
                pass
            return decoded

        monkeypatch.setattr(store, "_decode_text", decode_at_same_time)

    coordinate_decoder(first)
    coordinate_decoder(second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(store.pop_sensitive_input, waiting.work_id, "pairing_pin")
            for store in (first, second)
        ]
        results = [future.result(timeout=10) for future in futures]
    assert results.count("FICTIONAL_CONCURRENT_PIN_1739") == 1
    assert results.count(None) == 1
    assert (
        SQLiteWorkStore(path, payload_codec=codec).pop_sensitive_input(
            waiting.work_id, "pairing_pin"
        )
        is None
    )


def test_sensitive_input_decode_failure_preserves_value_and_releases_transaction(
    tmp_path, monkeypatch
):
    path = tmp_path / "work.sqlite"
    codec = ProtectedWorkPayloadCodec(b"p" * 32)
    first = SQLiteWorkStore(path, payload_codec=codec)
    waiting = _waiting(first)
    first.put_sensitive_input(
        waiting.work_id, "pairing_pin", "FICTIONAL_RETRY_PIN_1739"
    )
    second = SQLiteWorkStore(path, payload_codec=codec)

    def fail_decode(value):
        raise WorkPayloadProtectionError("synthetic decode failure")

    monkeypatch.setattr(first, "_decode_text", fail_decode)
    with pytest.raises(WorkPayloadProtectionError, match="synthetic"):
        first.pop_sensitive_input(waiting.work_id, "pairing_pin")
    assert (
        second.pop_sensitive_input(waiting.work_id, "pairing_pin")
        == "FICTIONAL_RETRY_PIN_1739"
    )
    assert second.pop_sensitive_input(waiting.work_id, "pairing_pin") is None
