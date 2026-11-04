import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)

from jarvis.voice.project_memory_development import (
    CASE_IDS,
    DevelopmentProvider,
    batch_summary,
    case_report,
    load_cases,
    run_case_question,
    run_development_batch,
    seed_development_case,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("checkout_newline", ["\n", "\r\n"])
def test_only_six_frozen_development_cases_and_windows_newlines(
    tmp_path, checkout_newline
):
    checkout = tmp_path / "checkout"
    originals = checkout / "tests/project_memory/fixtures"
    originals.mkdir(parents=True)
    for source in (REPO / "tests/project_memory/fixtures").glob("*-v1.json"):
        (originals / source.name).write_bytes(
            source.read_text(encoding="utf-8")
            .replace("\n", checkout_newline)
            .encode("utf-8")
        )
    cases = load_cases(checkout)
    assert tuple(c.question["id"] for c in cases) == CASE_IDS
    assert all(c.question["split"] == "development" for c in cases)
    assert all(len(c.events) == 60 for c in cases)
    fixtures = tmp_path / "converted/tests/project_memory/fixtures"
    fixtures.mkdir(parents=True)
    for source in originals.glob("*-v1.json"):
        (fixtures / source.name).write_bytes(
            source.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
        )
    assert load_cases(tmp_path / "converted") == cases
    with (fixtures / "events-v1.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="frozen"):
        load_cases(tmp_path / "converted")


@pytest.mark.asyncio
@pytest.mark.parametrize("case_index", range(6))
async def test_seed_sixty_originals_three_projects_scoped_and_nonrepeatable(
    empty_access,
    case_index,
):
    case = load_cases(REPO)[case_index]
    manifest = await seed_development_case(empty_access, case)
    catalog = await empty_access.catalog()
    assert len(catalog.entries) == 3
    assert catalog.current.project_id == manifest["project_id"]
    originals = {r["event_id"]: r for r in case.events}
    seen = set()
    for entry in catalog.entries:
        snapshot = await empty_access.snapshot(
            entry.selection, limit=128, project_wide=True
        )
        assert len(snapshot.sources) == 20
        for source in snapshot.sources:
            event = source.event
            row = originals[event.event_id]
            assert (event.text, event.role, event.request_id, event.delivery) == (
                row["text"],
                row["role"],
                row["request_id"],
                row["delivery"],
            )
            seen.add(event.event_id)
    assert seen == set(originals)
    before = empty_access.store.change_revision
    with pytest.raises(ValueError, match="empty"):
        await seed_development_case(empty_access, case)
    assert empty_access.store.change_revision == before


@pytest.mark.asyncio
async def test_revoked_seed_writes_nothing(empty_access):
    empty_access.authority.revoke(empty_access.grant)
    with pytest.raises(PermissionError):
        await seed_development_case(empty_access, load_cases(REPO)[0])
    assert empty_access.store.change_revision == 0


@pytest.mark.asyncio
async def test_revocation_mid_seed_keeps_partial_history_without_continuing(
    empty_access, monkeypatch
):
    original = empty_access.store.append_event
    committed = []

    async def append(*args, **kwargs):
        receipt = await original(*args, **kwargs)
        committed.append(receipt)
        if len(committed) == 5:
            empty_access.authority.revoke(empty_access.grant)
        return receipt

    monkeypatch.setattr(empty_access.store, "append_event", append)
    with pytest.raises(PermissionError):
        await seed_development_case(empty_access, load_cases(REPO)[0])
    assert len(committed) == 5


@pytest.mark.asyncio
async def test_real_coordinator_payload_never_contains_answer_key_or_foreign_sources(
    empty_access,
):
    from jarvis.voice.project_answer_provider import ProjectAnswerProvider
    from jarvis.voice.project_conversation import ProjectConversationCoordinator

    case = load_cases(REPO)[0]
    manifest = await seed_development_case(empty_access, case)
    payloads = []

    class Wire:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payloads.append(kwargs["input_payload"])
            response = (
                {"search_query": "chosen resource"}
                if len(payloads) == 1
                else {"answer": "Jimny"}
            )
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=response),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=lambda _: True
    )
    report = await run_case_question(
        case, manifest, coordinator, empty_access, ProjectAnswerProvider(Wire())
    )
    assert report["expected_sources_in_final_context"] == ["p0-e2"]
    assert report["foreign_fixture_sources_seen"] == []
    assert report["answer_quality"] == "manual_review_required"
    assert report["usage"]["total_tokens"] is None
    assert report["usage"]["unknown_steps"] == 2
    for payload in payloads:
        assert "expected" not in payload and "rubric" not in payload
        assert not {"p1", "p2"} & {
            s["source_id"].split("-")[0] for s in payload["context"]["sources"]
        }


@pytest.mark.asyncio
async def test_foreign_scope_blocked_before_any_provider_call():
    called = []

    class Provider:
        async def step(self, *args, **kwargs):
            called.append(True)

    observer = DevelopmentProvider(
        Provider(),
        {
            "project_id": "target",
            "thread_id": "t",
            "target_source_ids": ["p0-e2"],
            "seeded_source_ids": ["p0-e2", "p1-e2"],
        },
    )
    packet = SimpleNamespace(
        selection=SimpleNamespace(project_id="target", thread_id="t"),
        source_ids=("p1-e2",),
    )
    with pytest.raises(PermissionError, match="scope"):
        await observer.step(packet, check=lambda: True)
    assert not called
    assert observer.foreign_ids == {"p1-e2"}


def test_metrics_do_not_hide_unknown_usage_or_mix_failed_latency():
    case = load_cases(REPO)[0]
    result = SimpleNamespace(
        answer="Jimny",
        usage=[
            {"observed": True, "usage": {"total_tokens": 100}, "latency_ms": 2},
            {"observed": False, "usage": {"total_tokens": 999}, "latency_ms": None},
        ],
        packet=SimpleNamespace(request_id="r", revision="h", source_ids=("p0-e2",)),
    )
    report = case_report(
        case,
        {},
        result,
        SimpleNamespace(foreign_ids=set(), contexts_seen=2),
        elapsed_ms=10,
    )
    assert report["usage"] == {
        "total_tokens": None,
        "known_total_tokens": 100,
        "unknown_steps": 1,
    }
    assert report["provider_latency_ms"] is None
    summary = batch_summary(
        [report, {"case_id": "p1-q1", "status": "failed", "elapsed_ms": 999}], CASE_IDS
    )
    assert summary["completed"] == 1 and summary["failed"] == 1
    assert summary["unrun"] == list(CASE_IDS[2:])
    assert summary["turn_latency_ms"] == {"sample_count": 1, "p50": 10, "p95": 10}
    assert summary["answer_quality"] == "manual_review_required"
    assert summary["provider_latency_ms"]["sample_count"] == 0
    assert summary["usage"]["total_tokens"] is None
    assert summary["usage"]["known_total_tokens"] == 100


def test_summary_observed_totals_and_small_sample_nearest_rank():
    rows = [
        {
            "case_id": ident,
            "status": "completed",
            "elapsed_ms": n * 10,
            "provider_latency_ms": n * 5,
            "returned_provider_steps": 2,
            "usage": {
                "total_tokens": n * 100,
                "known_total_tokens": n * 100,
                "unknown_steps": 0,
            },
        }
        for n, ident in enumerate(CASE_IDS, 1)
    ]
    report = batch_summary(rows, CASE_IDS)
    assert report["turn_latency_ms"] == {"sample_count": 6, "p50": 30, "p95": 60}
    assert report["provider_latency_ms"] == {"sample_count": 6, "p50": 15, "p95": 30}
    assert report["usage"]["total_tokens"] == 2100
    assert report["returned_provider_steps"] == 12


def test_batch_fresh_roots_partial_report_and_stop_first_failure(tmp_path):
    root = tmp_path / "batch"
    cases = load_cases(REPO)
    called = []

    def run_case(case, path):
        called.append(path)
        assert not path.exists()
        path.mkdir()
        if len(called) == 2:
            raise PermissionError("private diagnostic must not be copied")
        return {"case_id": case.question["id"], "status": "completed", "elapsed_ms": 4}

    summary = run_development_batch(
        root, cases, run_case, source_commit="a" * 40, model="configured-model"
    )
    rows = [json.loads(s) for s in (root / "results.jsonl").read_text().splitlines()]
    assert len(called) == len(rows) == 2 and called[0] != called[1]
    assert rows[1][
        "error"
    ] == "PermissionError" and "private diagnostic" not in json.dumps(rows)
    assert summary["unrun"] == list(CASE_IDS[2:])
    assert json.loads((root / "summary.json").read_text()) == summary
    with pytest.raises(FileExistsError):
        run_development_batch(
            root, cases, run_case, source_commit="a" * 40, model="configured-model"
        )
    assert len(called) == 2


@pytest.mark.asyncio
async def test_one_question_failure_never_retries_or_commits_an_assistant(empty_access):
    from jarvis.voice.project_conversation import ProjectConversationCoordinator

    case = load_cases(REPO)[0]
    manifest = await seed_development_case(empty_access, case)
    calls = []

    class Failure:
        async def step(self, packet, **kwargs):
            calls.append(packet.request_id)
            raise ValueError("provider failed")

    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=lambda _: True
    )
    with pytest.raises(ValueError, match="provider failed"):
        await run_case_question(case, manifest, coordinator, empty_access, Failure())
    snapshot = await empty_access.snapshot(
        (await empty_access.catalog()).current, limit=128
    )
    assert len(calls) == 1
    assert len(snapshot.sources) == 21
    assert snapshot.sources[-1].event.role == "user"


@pytest.mark.parametrize("extra", ["--seed-acceptance", "--resume-lab"])
def test_batch_mode_rejects_conflicting_modes_before_platform_operations(
    monkeypatch, capsys, extra
):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            "unused",
            "--model",
            "unused",
            "--source-commit",
            "a" * 40,
            "--development-batch",
            extra,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "development batch requires a new" in capsys.readouterr().err


def test_lab_batch_orchestration_creates_six_profiles_and_invokes_scripted_mode(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from jarvis.voice import project_memory_lab as lab

    profiles = []
    active = []
    calls = []

    def prepare(source, root, **kwargs):
        assert kwargs["resume"] is False and not root.exists()
        root.mkdir()
        profiles.append(root)
        return root / "machine.json"

    @contextmanager
    def environment(profile, repo):
        active.append(profile.parent)
        try:
            yield
        finally:
            active.pop()

    async def run(config, root, *, model, development_case):
        assert active == [root]
        assert config.ai_provider == "gemini"
        calls.append(development_case.question["id"])
        return {"case_id": calls[-1], "status": "completed", "elapsed_ms": 1}

    monkeypatch.setattr(lab, "prepare_project_profile", prepare)
    monkeypatch.setattr(lab, "project_lab_environment", environment)
    monkeypatch.setattr(lab, "run_text_lab", run)
    monkeypatch.setattr(
        "jarvis.config.JarvisConfig.from_environment",
        lambda: SimpleNamespace(ai_provider="gemini"),
    )
    args = SimpleNamespace(
        profile=tmp_path / "owner.json",
        lab_root=tmp_path / "batch",
        source_commit="a" * 40,
        model="configured",
    )
    summary = lab.run_development_mode(args, REPO, {})
    assert calls == list(CASE_IDS) and len(set(profiles)) == 6
    assert summary["completed"] == 6 and not active


def test_closed_console_still_saves_summary_and_stops_without_repeating(
    tmp_path, monkeypatch
):
    import builtins

    root = tmp_path / "batch"
    calls = []
    original_print = builtins.print

    def print_result(*args, **kwargs):
        if args and str(args[0]).startswith("DEVELOPMENT_CASE"):
            raise BrokenPipeError("closed output")
        return original_print(*args, **kwargs)

    def run(case, path):
        calls.append(case.question["id"])
        return {"case_id": calls[-1], "status": "completed", "elapsed_ms": 1}

    monkeypatch.setattr(builtins, "print", print_result)
    summary = run_development_batch(
        root, load_cases(REPO), run, source_commit="a" * 40, model="configured"
    )
    assert calls == [CASE_IDS[0]]
    assert summary["completed"] == 1 and summary["unrun"] == list(CASE_IDS[1:])
    assert summary["reporting_errors"] == [
        {"channel": "console", "error": "BrokenPipeError", "case_id": CASE_IDS[0]}
    ]
    assert json.loads((root / "summary.json").read_text()) == summary
    assert len((root / "results.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_jsonl_failure_preserves_terminal_result_in_summary_and_stops(
    tmp_path, monkeypatch, failure
):
    root = tmp_path / "batch"
    calls = []
    original_open = Path.open

    class FailedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def write(self, data):
            if failure == "write":
                raise OSError("write unavailable")
            return self.stream.write(data)

        def flush(self):
            raise OSError("flush unavailable")

        def close(self):
            self.stream.close()

    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return (
            FailedStream(stream)
            if path.name == "results.jsonl" and args[0] == "x"
            else stream
        )

    def run(case, path):
        calls.append(case.question["id"])
        return {
            "case_id": calls[-1],
            "status": "completed",
            "elapsed_ms": 1,
            "answer": "synthetic answer",
        }

    monkeypatch.setattr(Path, "open", open_file)
    summary = run_development_batch(
        root, load_cases(REPO), run, source_commit="a" * 40, model="configured"
    )
    assert calls == [CASE_IDS[0]]
    assert summary["unrun"] == list(CASE_IDS[1:])
    assert summary["reporting_errors"] == [
        {"channel": "results_jsonl", "error": "OSError", "case_id": CASE_IDS[0]}
    ]
    assert summary["terminal_case_result"]["answer"] == "synthetic answer"
    assert json.loads((root / "summary.json").read_text()) == summary


def test_closed_summary_console_is_recorded_in_exclusive_summary_file(
    tmp_path, monkeypatch
):
    import builtins

    original_print = builtins.print

    def print_result(*args, **kwargs):
        if args and str(args[0]).startswith("DEVELOPMENT_SUMMARY"):
            raise BrokenPipeError("closed output")
        return original_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", print_result)
    root = tmp_path / "batch"
    summary = run_development_batch(
        root,
        load_cases(REPO),
        lambda case, _: {
            "case_id": case.question["id"],
            "status": "completed",
            "elapsed_ms": 1,
        },
        source_commit="a" * 40,
        model="configured",
    )
    assert summary["completed"] == 6 and summary["unrun"] == []
    assert summary["reporting_errors"] == [
        {"channel": "console", "error": "BrokenPipeError", "case_id": None}
    ]
    assert json.loads((root / "summary.json").read_text()) == summary


def test_unavailable_jsonl_stops_before_any_question_and_marks_all_unrun(
    tmp_path, monkeypatch
):
    original_open = Path.open

    def open_file(path, *args, **kwargs):
        if path.name == "results.jsonl":
            raise OSError("unavailable")
        return original_open(path, *args, **kwargs)

    def no_question(*args):
        pytest.fail("question ran before result file was opened")

    monkeypatch.setattr(Path, "open", open_file)
    root = tmp_path / "batch"
    summary = run_development_batch(
        root, load_cases(REPO), no_question, source_commit="a" * 40, model="configured"
    )
    assert summary["completed"] == 0 and summary["unrun"] == list(CASE_IDS)
    assert summary["reporting_errors"] == [
        {"channel": "results_jsonl", "error": "OSError", "case_id": None}
    ]
    assert json.loads((root / "summary.json").read_text()) == summary


def test_selected_development_case_runs_once_with_its_frozen_history(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from jarvis.voice import project_memory_lab as lab

    calls = []

    def prepare(source, root, **kwargs):
        assert kwargs["resume"] is False
        root.mkdir()
        return root / "machine.json"

    @contextmanager
    def environment(*args):
        yield

    async def run(config, root, *, model, development_case):
        assert len(development_case.events) == 60
        calls.append(development_case.question["id"])
        return {"case_id": calls[-1], "status": "completed", "elapsed_ms": 1}

    monkeypatch.setattr(lab, "prepare_project_profile", prepare)
    monkeypatch.setattr(lab, "project_lab_environment", environment)
    monkeypatch.setattr(lab, "run_text_lab", run)
    monkeypatch.setattr(
        "jarvis.config.JarvisConfig.from_environment",
        lambda: SimpleNamespace(ai_provider="gemini"),
    )
    args = SimpleNamespace(
        profile=tmp_path / "owner.json",
        lab_root=tmp_path / "batch",
        source_commit="a" * 40,
        model="configured",
        development_case="p5-q5",
    )
    summary = lab.run_development_mode(args, REPO, {})
    assert calls == ["p5-q5"]
    assert summary["planned"] == summary["completed"] == 1


@pytest.mark.parametrize(
    "extra,reason",
    [
        ([], "requires --development-batch"),
        (["--development-batch", "--resume-lab"], "development batch requires a new"),
    ],
)
def test_case_mode_guard_precedes_platform_and_profile_operations(
    monkeypatch, capsys, extra, reason
):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            "unused",
            "--model",
            "configured",
            "--source-commit",
            "a" * 40,
            "--development-case",
            "p5-q5",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert reason in capsys.readouterr().err


def test_held_out_case_cannot_be_selected(monkeypatch, capsys):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            "unused",
            "--model",
            "configured",
            "--source-commit",
            "a" * 40,
            "--development-batch",
            "--development-case",
            "p0-q9",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
