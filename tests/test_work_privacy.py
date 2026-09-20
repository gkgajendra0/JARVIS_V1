from __future__ import annotations

from pathlib import Path

from jarvis.work.models import WorkDeliveryKind, WorkItem, WorkStep, WorkType
from jarvis.work.privacy import build_protected_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


class FakeKeyProtector:
    protector_id = "fake-test-protector"

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


def test_protected_work_store_round_trips_without_plaintext_payloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite"
    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"k" * size,
    )
    store = SQLiteWorkStore(path, payload_codec=codec)
    marker = "SUPER_SECRET_WORK_PROMPT_9017"
    item = WorkItem(
        request=marker,
        work_type=WorkType.GENERIC,
        source_session_id="session-private",
        source_turn_id="turn-private",
    )
    store.create(item)
    running = item.transition(
        item.state.RUNNING,
        status_detail="private status detail",
    )
    store.save(running, expected_version=item.version)
    step = WorkStep(
        work_id=item.work_id,
        kind="private_step",
        summary="private summary",
        input_data={"secret": marker},
    )
    store.add_step(step)
    store.save_step(step.start().complete({"result": marker}))
    store.enqueue_delivery(
        work=running,
        kind=WorkDeliveryKind.COMPLETION,
        message=marker,
        event_key="private-completion",
    )

    assert marker.encode("utf-8") not in _raw_storage(path)

    reopened = SQLiteWorkStore(path, payload_codec=codec)
    assert reopened.require(item.work_id).request == marker
    assert reopened.list_steps(item.work_id)[0].input_data["secret"] == marker
    assert reopened.list_pending_deliveries()[0].message == marker


def test_protected_store_migrates_existing_plaintext_payloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite"
    marker = "LEGACY_PRIVATE_WORK_PROMPT_3141"
    plaintext = SQLiteWorkStore(path)
    item = WorkItem(
        request=marker,
        work_type=WorkType.GENERIC,
        source_session_id="session-legacy",
        source_turn_id="turn-legacy",
    )
    plaintext.create(item)
    assert marker.encode("utf-8") in _raw_storage(path)

    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"m" * size,
    )
    protected = SQLiteWorkStore(path, payload_codec=codec)
    migrated = protected.protect_existing_payloads()

    assert migrated >= 1
    assert marker.encode("utf-8") not in _raw_storage(path)
    assert protected.require(item.work_id).request == marker
