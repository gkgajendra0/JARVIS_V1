"""Real canonical storage/coordinator; fictional data and fake OS/model only."""

import json
from types import SimpleNamespace

import pytest
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.service import MemoryService
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator
from jarvis.voice.project_memory_lab import build_project_personal_session


def runtime(
    access, parts, *, skip_personal=False, deny_correction=False, known_usage=False
):
    store = access.store
    memory = SimpleNamespace(
        service=MemoryService(
            MemoryLifecycleService(store._writer), CanonicalMemoryReader(store._reader)
        ),
        retrieval=SemanticRetrievalService(store._reader),
    )
    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=parts.broker,
    )
    coordinator = ProjectConversationCoordinator(
        access,
        source_clearance=lambda _: True,
        personal_factory=lambda c: build_project_personal_session(
            c, memory, capability
        ),
    )
    payloads = []

    class Wire:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payload = kwargs["input_payload"]
            payloads.append(payload)
            if payload["available_tools"]["personal_available"] and not skip_personal:
                response = {"personal_requests": [{"scope_key": "food_preference"}]}
            else:
                response = {"answer": "Fictional reply; manual grading is separate."}
                if deny_correction and len(payloads) == 4:
                    parts.hello.denied = True
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=response),
                usage={"total_tokens": 123} if known_usage else {},
                usage_observed=known_usage,
                latency_ms=1,
            )

    return memory, capability, coordinator, ProjectAnswerProvider(Wire()), payloads


@pytest.mark.asyncio
async def test_canonical_personal_fact_crosses_projects_and_correction_replaces_it(
    empty_access, authority_parts, tmp_path
):
    from jarvis.voice.project_personal_acceptance import run_personal_acceptance

    memory, capability, coordinator, provider, payloads = runtime(
        empty_access, authority_parts
    )
    root = tmp_path / "report"
    root.mkdir()
    try:
        summary = await run_personal_acceptance(
            root,
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=provider,
        )
        assert summary["completed"] == 3
        assert summary["failed"] == 0
        assert summary["answer_quality"] == "manual_review_required"
        rows = [
            json.loads(line)
            for line in (root / "personal-results.jsonl").read_text().splitlines()
        ]
        questions = [r for r in rows if r["kind"] == "question"]
        mutations = [r for r in rows if r["kind"] == "mutation"]
        assert [r["operation"] for r in mutations] == ["remember", "correct"]
        assert len(payloads) == 6
        assert [
            r["personal_evidence"]["expected_assertion_selected"] for r in questions
        ] == [True] * 3
        assert all(
            r["personal_evidence"]["expected_fact_in_final_context"] for r in questions
        )
        assert all(
            not r["personal_evidence"]["stale_assertion_selected"] for r in questions
        )
        assert questions[0]["project_id"] != questions[1]["project_id"]
        assert questions[0]["project_id"] == questions[2]["project_id"]
        assert questions[0]["thread_id"] != questions[2]["thread_id"]
        for index, payload in enumerate(payloads):
            assert "expected" not in json.dumps(payload)
            if index in (0, 2):
                assert "vegetarian" not in json.dumps(payload)
            if index == 4:
                assert "vegan" not in json.dumps(payload)
        assert (
            payloads[1]["context"]["personal"]["facts"][0]["text"]
            == "diet preference: vegetarian"
        )
        assert (
            payloads[3]["context"]["personal"]["facts"][0]["text"]
            == "diet preference: vegetarian"
        )
        assert (
            payloads[5]["context"]["personal"]["facts"][0]["text"]
            == "diet preference: vegan"
        )
        assert questions[0]["usage"]["total_tokens"] is None
        with pytest.raises(FileExistsError):
            await run_personal_acceptance(
                root,
                memory=memory,
                capability=capability,
                coordinator=coordinator,
                access=empty_access,
                provider=provider,
            )
        assert len(payloads) == 6
    finally:
        coordinator.invalidate("test_end")
        # The shared broker is owned by empty_access, which closes its grant.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["denied_seed", "denied_correction", "missing_evidence"]
)
async def test_failed_personal_acceptance_stops_and_keeps_partial_evidence(
    empty_access, authority_parts, tmp_path, mode
):
    from jarvis.voice.project_personal_acceptance import run_personal_acceptance

    memory, capability, coordinator, provider, payloads = runtime(
        empty_access,
        authority_parts,
        skip_personal=mode == "missing_evidence",
        deny_correction=mode == "denied_correction",
    )
    if mode == "denied_seed":
        authority_parts.hello.denied = True
    root = tmp_path / "partial"
    root.mkdir()
    try:
        with pytest.raises(PermissionError):
            await run_personal_acceptance(
                root,
                memory=memory,
                capability=capability,
                coordinator=coordinator,
                access=empty_access,
                provider=provider,
            )
        summary = json.loads((root / "personal-summary.json").read_text())
        assert summary["failed"] == 1
        assert (
            len(payloads)
            == {"denied_seed": 0, "denied_correction": 4, "missing_evidence": 1}[mode]
        )
        rows = [
            json.loads(line)
            for line in (root / "personal-results.jsonl").read_text().splitlines()
        ]
        assert rows[-1]["kind"] == "failure"
        assert "message" not in rows[-1]
        if mode == "missing_evidence":
            assert summary["unrun"] == ["study_shared", "travel_corrected"]
        if mode == "denied_correction":
            assert len([r for r in rows if r["kind"] == "question"]) == 2
            assert (
                await memory.service.inspect_exact(predicate="diet preference")
            ).record.value == "vegetarian"
    finally:
        coordinator.invalidate("test_end")
        # The shared broker is owned by empty_access, which closes its grant.


@pytest.mark.asyncio
async def test_existing_summary_prevents_any_canonical_mutation(
    empty_access, authority_parts, tmp_path
):
    from jarvis.voice.project_personal_acceptance import run_personal_acceptance

    memory, capability, coordinator, provider, payloads = runtime(
        empty_access, authority_parts
    )
    (tmp_path / "personal-summary.json").write_text("retained")
    with pytest.raises(FileExistsError):
        await run_personal_acceptance(
            tmp_path,
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=provider,
        )
    assert (await memory.retrieval.learning_context_snapshot()).entries == ()
    assert payloads == []
    assert (tmp_path / "personal-summary.json").read_text() == "retained"


@pytest.mark.parametrize(
    "extra", ["--resume-lab", "--seed-acceptance", "--development-batch"]
)
def test_personal_mode_combinations_rejected_before_profile_work(
    tmp_path, monkeypatch, capsys, extra
):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            str(tmp_path / "absent"),
            "--source-commit",
            "a" * 40,
            "--model",
            "fictional",
            "--personal-acceptance",
            extra,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert (
        "personal acceptance requires a fresh standalone lab" in capsys.readouterr().err
    )
    assert not (tmp_path / "absent").exists()


@pytest.mark.asyncio
async def test_summary_write_failure_does_not_replace_denied_approval(
    empty_access, authority_parts, tmp_path, monkeypatch
):
    from pathlib import Path

    from jarvis.voice.project_personal_acceptance import run_personal_acceptance

    memory, capability, coordinator, provider, _ = runtime(
        empty_access, authority_parts
    )
    authority_parts.hello.denied = True
    original = Path.open

    class BrokenSummary:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, text):
            raise OSError("PRIVATE_DISK_ERROR")

        def flush(self):
            pass

        def close(self):
            pass

    def open_file(path, *args, **kwargs):
        return (
            BrokenSummary()
            if path.name == "personal-summary.json"
            else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(PermissionError):
        await run_personal_acceptance(
            tmp_path,
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=provider,
        )


def test_runtime_cleanup_failure_updates_summary_without_losing_completed_rows(
    tmp_path,
):
    from jarvis.voice.project_personal_acceptance import record_runtime_failure

    (tmp_path / "personal-summary.json").write_text(
        json.dumps({"completed": 3, "failed": 0, "unrun": []})
    )
    (tmp_path / "personal-results.jsonl").write_text("retained question evidence\n")
    report = {
        "stage": "cleanup",
        "error": "OSError",
        "cleanup_errors": [{"component": "routing", "error": "OSError"}],
    }
    record_runtime_failure(tmp_path, report)
    saved = json.loads((tmp_path / "personal-summary.json").read_text())
    assert saved["failed"] == 1 and saved["completed"] == 3
    assert saved["runtime_failure"] == report
    assert (
        tmp_path / "personal-results.jsonl"
    ).read_text() == "retained question evidence\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["partial_write", "flush"])
async def test_partial_question_journal_preserves_terminal_answer_and_known_usage(
    empty_access, authority_parts, tmp_path, monkeypatch, failure
):
    from pathlib import Path

    from jarvis.voice.project_personal_acceptance import run_personal_acceptance

    memory, capability, coordinator, provider, payloads = runtime(
        empty_access, authority_parts, known_usage=True
    )
    original = Path.open

    class PartialJournal:
        def __init__(self, stream):
            self.stream, self.writes = stream, 0

        def write(self, text):
            self.writes += 1
            if self.writes == 2 and failure == "partial_write":
                self.stream.write(text[:37])
                self.stream.flush()
                raise OSError("PRIVATE_PARTIAL_WRITE")
            return self.stream.write(text)

        def flush(self):
            self.stream.flush()
            if self.writes == 2 and failure == "flush":
                raise OSError("PRIVATE_PARTIAL_WRITE")

        def close(self):
            self.stream.close()

    def open_file(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return (
            PartialJournal(stream) if path.name == "personal-results.jsonl" else stream
        )

    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(OSError, match="PRIVATE_PARTIAL_WRITE"):
        await run_personal_acceptance(
            tmp_path,
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=provider,
        )
    saved = json.loads((tmp_path / "personal-summary.json").read_text())
    terminal = saved["terminal_case_result"]
    assert terminal["answer"] == "Fictional reply; manual grading is separate."
    assert terminal["usage"]["total_tokens"] == 246
    assert terminal["personal_evidence"]["expected_assertion_selected"] is True
    assert saved["unrun"] == ["study_shared", "travel_corrected"]
    assert saved["failed"] == 1
    assert len(payloads) == 2
    assert "PRIVATE" not in json.dumps(saved)
