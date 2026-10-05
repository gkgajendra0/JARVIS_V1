import re
from pathlib import Path

from jarvis.autonomy import (
    GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1,
    ShadowFaultKind,
    validate_global_supervisor_s11_fault_matrix,
)
from jarvis.system_replay import (
    GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1,
    SystemReplayStatus,
    global_supervisor_s1_known_gap_ids,
    global_supervisor_s1_pytest_node_ids,
    global_supervisor_s1_replay_corpus_digest,
    validate_global_supervisor_s1_replay_corpus,
)


def test_global_supervisor_s1_replay_corpus_is_locked_and_complete() -> None:
    validate_global_supervisor_s1_replay_corpus()

    assert len(GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1) == 20
    assert tuple(case.case_id for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1) == (
        "01-research-provider-overload",
        "02-development-provider-overload",
        "03-malformed-model-structured-output",
        "04-codex-contract-repair",
        "05-temporary-resource-wait",
        "06-failed-research-replaced-by-success",
        "07-superseded-work-cannot-poison-current-work",
        "08-target-incompatible-candidate",
        "09-pypi-url-package-identity",
        "10-architecture-revision",
        "11-new-architecture-new-approval",
        "12-restart-during-active-research",
        "13-restart-during-development",
        "14-restart-after-owner-approval",
        "15-duplicate-dbos-replay",
        "16-developer-requests-more-research",
        "17-research-answer-resumes-development",
        "18-verification-rejects-implementation",
        "19-owner-input-required",
        "20-tv-goal-full-lifecycle",
    )
    assert global_supervisor_s1_replay_corpus_digest() == (
        global_supervisor_s1_replay_corpus_digest()
    )


def test_global_supervisor_s1_replay_corpus_tracks_known_gaps_explicitly() -> None:
    assert global_supervisor_s1_known_gap_ids() == (
        "07-superseded-work-cannot-poison-current-work",
        "08-target-incompatible-candidate",
    )

    live_cases = tuple(
        case.case_id
        for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
        if case.status is SystemReplayStatus.LIVE_ACCEPTANCE_PENDING
    )
    assert live_cases == ("20-tv-goal-full-lifecycle",)

    covered = tuple(
        case.case_id
        for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
        if case.status is SystemReplayStatus.COVERED
    )
    assert len(covered) == 17


def test_global_supervisor_s1_replay_evidence_nodes_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    for node_id in global_supervisor_s1_pytest_node_ids():
        relative_path, test_name = node_id.split("::", 1)
        source_path = repo_root / relative_path
        assert source_path.is_file(), node_id

        source = source_path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"^(?:async\s+)?def\s+{re.escape(test_name)}\s*\(",
            re.MULTILINE,
        )
        assert pattern.search(source), node_id


def test_global_supervisor_s1_replay_is_observational_only() -> None:
    assert all(
        case.owning_phase == "S1"
        for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
        if case.status is SystemReplayStatus.COVERED
    )
    assert {
        case.case_id: case.owning_phase
        for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
        if case.status is not SystemReplayStatus.COVERED
    } == {
        "07-superseded-work-cannot-poison-current-work": "S3-S4",
        "08-target-incompatible-candidate": "S6",
        "20-tv-goal-full-lifecycle": "S13",
    }


def test_global_supervisor_s11_fault_matrix_is_complete() -> None:
    validate_global_supervisor_s11_fault_matrix()

    assert tuple(item.fault_kind for item in GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1) == (
        ShadowFaultKind.PROVIDER_OUTAGE,
        ShadowFaultKind.MALFORMED_RESPONSE,
        ShadowFaultKind.STALE_ARTIFACT,
        ShadowFaultKind.DUPLICATE_EVENT,
        ShadowFaultKind.PROCESS_CRASH,
        ShadowFaultKind.IRRELEVANT_CANDIDATE,
        ShadowFaultKind.SPECIALIST_LOOP,
        ShadowFaultKind.FAILED_DEPENDENCY,
    )


def test_global_supervisor_s11_fault_evidence_nodes_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    for case in GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1:
        for node_id in case.evidence_tests:
            relative_path, test_name = node_id.split("::", 1)
            source_path = repo_root / relative_path
            assert source_path.is_file(), node_id

            source = source_path.read_text(encoding="utf-8")
            pattern = re.compile(
                rf"^(?:async\s+)?def\s+{re.escape(test_name)}\s*\(",
                re.MULTILINE,
            )
            assert pattern.search(source), node_id
