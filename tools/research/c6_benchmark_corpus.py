"""Deterministic C6 decision-equivalence benchmark corpus.

The cases mirror real WorkEngine workflow shapes already covered by repository tests,
but import production BrainAction descriptors directly. No executor is instantiated
and no Work action can run from this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.sdk_verification import (
    AcquisitionVerifyPyPiSdkExecutor,
)
from jarvis.capability_acquisition.workflow import (
    AcquisitionFinalizeExecutor,
    AcquisitionInspectGoalExecutor,
    AcquisitionRecordCandidateExecutor,
    AcquisitionResolveExecutor,
)
from jarvis.work.actions import ResearchWorkExecutor
from jarvis.work.brain import BrainAction, BrainRequest
from jarvis.work.context import WorkContextAssembler, WorkContextMode
from jarvis.work.development import (
    DevelopmentCommitExecutor,
    DevelopmentDiffExecutor,
    DevelopmentListFilesExecutor,
    DevelopmentReadFileExecutor,
    DevelopmentRunTestsExecutor,
    DevelopmentSearchExecutor,
    DevelopmentStatusExecutor,
    DevelopmentWriteFileExecutor,
    PrepareDevelopmentWorkspaceExecutor,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType

_PURPOSE = "choose the next bounded step for this JARVIS-owned work item"


@dataclass(frozen=True, slots=True)
class C6BenchmarkCase:
    case_id: str
    rationale: str
    request: BrainRequest


def _complete(
    work_id: str,
    index: int,
    kind: str,
    summary: str,
    *,
    input_data: dict | None = None,
    observation: dict | None = None,
) -> WorkStep:
    return (
        WorkStep(
            work_id=work_id,
            kind=kind,
            summary=summary,
            step_id=f"step_{work_id}_{index:03d}",
            input_data=dict(input_data or {}),
        )
        .start()
        .complete(dict(observation or {}))
    )


def _fail(
    work_id: str,
    index: int,
    kind: str,
    summary: str,
    *,
    input_data: dict | None = None,
    reason: str,
) -> WorkStep:
    return (
        WorkStep(
            work_id=work_id,
            kind=kind,
            summary=summary,
            step_id=f"step_{work_id}_{index:03d}",
            input_data=dict(input_data or {}),
        )
        .start()
        .fail(reason)
    )


def _request(
    *,
    work_id: str,
    request_text: str,
    work_type: WorkType,
    steps: tuple[WorkStep, ...],
    actions: tuple[BrainAction, ...],
    assembler: WorkContextAssembler,
) -> BrainRequest:
    work = WorkItem(
        work_id=work_id,
        request=request_text,
        work_type=work_type,
        source_session_id="session-c6-benchmark",
        source_turn_id=f"turn-{work_id}",
        state=WorkState.RUNNING,
        current_step_id=steps[-1].step_id,
        status_detail="reasoning",
        version=max(2, len(steps) + 1),
    )
    pack = assembler.build(work=work, steps=steps)
    return BrainRequest(
        work=work,
        recent_steps=steps[-12:],
        purpose=_PURPOSE,
        allowed_actions=actions,
        full_history_steps=steps,
        context_pack=pack,
        context_mode=WorkContextMode.APPLY,
    )


def _development_actions() -> tuple[BrainAction, ...]:
    return (
        PrepareDevelopmentWorkspaceExecutor.descriptor,
        DevelopmentListFilesExecutor.descriptor,
        DevelopmentReadFileExecutor.descriptor,
        DevelopmentSearchExecutor.descriptor,
        DevelopmentWriteFileExecutor.descriptor,
        DevelopmentRunTestsExecutor.descriptor,
        DevelopmentDiffExecutor.descriptor,
        DevelopmentCommitExecutor.descriptor,
        DevelopmentStatusExecutor.descriptor,
    )


def _research_actions() -> tuple[BrainAction, ...]:
    return (
        ResearchWorkExecutor.descriptor,
        AcquisitionInspectGoalExecutor.descriptor,
        AcquisitionRecordCandidateExecutor.descriptor,
        AcquisitionVerifyPyPiSdkExecutor.descriptor,
        AcquisitionResolveExecutor.descriptor,
        AcquisitionFinalizeExecutor.descriptor,
    )


def _development_repair_case(
    assembler: WorkContextAssembler,
) -> C6BenchmarkCase:
    work_id = "c6_bench_dev_repair"
    steps: list[WorkStep] = [
        _complete(
            work_id,
            1,
            "dev_prepare_workspace",
            "Prepared isolated worktree.",
            observation={
                "prepared": True,
                "branch": "jarvis/work/c6-bench-dev-repair",
                "base_revision": "a" * 40,
                "production_tree_modified": False,
            },
        ),
        _complete(
            work_id,
            2,
            "dev_list_files",
            "Listed relevant source and tests.",
            observation={
                "files": [
                    "src/jarvis/example.py",
                    "src/jarvis/helper.py",
                    "tests/test_example.py",
                ],
                "truncated": False,
            },
        ),
    ]
    index = 3
    for number in range(8):
        steps.append(
            _complete(
                work_id,
                index,
                "dev_read_file",
                f"Inspected source file {number}.",
                input_data={"path": f"src/jarvis/module_{number}.py"},
                observation={
                    "path": f"src/jarvis/module_{number}.py",
                    "text": (
                        f"def bounded_{number}(value):\n"
                        "    # representative source context\n"
                        "    return value\n"
                    )
                    * 80,
                    "truncated": False,
                },
            )
        )
        index += 1
    for number in range(5):
        steps.append(
            _complete(
                work_id,
                index,
                "dev_search",
                f"Searched for affected symbol {number}.",
                input_data={"query": f"bounded_{number}"},
                observation={
                    "query": f"bounded_{number}",
                    "matches": [
                        {
                            "path": f"src/jarvis/module_{number}.py",
                            "line": number + 10,
                            "text": f"def bounded_{number}(value):",
                        }
                    ],
                    "truncated": False,
                },
            )
        )
        index += 1
    steps.extend(
        (
            _complete(
                work_id,
                index,
                "dev_write_file",
                "Applied the first bounded implementation.",
                input_data={
                    "path": "src/jarvis/example.py",
                    "text": (
                        "def normalize(value):\n"
                        "    # bounded implementation context\n"
                        "    return value.strip()\n"
                    )
                    * 110,
                },
                observation={
                    "path": "src/jarvis/example.py",
                    "bytes_written": 48,
                    "production_tree_modified": False,
                },
            ),
            _complete(
                work_id,
                index + 1,
                "dev_run_tests",
                "Initial sandboxed regression run reported a failing test.",
                input_data={"targets": ["tests/test_example.py"]},
                observation={
                    "passed": False,
                    "returncode": 1,
                    "timed_out": False,
                    "output": (
                        "FAILED tests/test_example.py::test_whitespace_only - "
                        "AssertionError: expected empty normalized value\n"
                    )
                    * 130,
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "-q",
                        "tests/test_example.py",
                    ],
                    "sandbox": "docker",
                    "network": "disabled",
                    "workspace": "read_only",
                    "sandbox_profile": "test.offline.v1",
                    "sandbox_profile_version": 1,
                },
            ),
            _complete(
                work_id,
                index + 2,
                "dev_read_file",
                "Re-read the failing test and implementation.",
                input_data={"path": "tests/test_example.py"},
                observation={
                    "path": "tests/test_example.py",
                    "text": (
                        "def test_whitespace_only():\n"
                        "    assert normalize('   ') == ''\n"
                    )
                    * 130,
                    "truncated": False,
                },
            ),
            _complete(
                work_id,
                index + 3,
                "dev_write_file",
                "Corrected the implementation after the failing test.",
                input_data={
                    "path": "src/jarvis/example.py",
                    "text": (
                        "def normalize(value):\n"
                        "    cleaned = value.strip()\n"
                        "    # preserve bounded normalization semantics\n"
                        "    return cleaned\n"
                    )
                    * 95,
                },
                observation={
                    "path": "src/jarvis/example.py",
                    "bytes_written": 76,
                    "production_tree_modified": False,
                },
            ),
            _complete(
                work_id,
                index + 4,
                "dev_run_tests",
                "Sandboxed regression tests passed after the repair.",
                input_data={"targets": ["tests/test_example.py"]},
                observation={
                    "passed": True,
                    "returncode": 0,
                    "timed_out": False,
                    "output": (
                        "tests/test_example.py::test_normalize PASSED\n"
                        "tests/test_example.py::test_whitespace_only PASSED\n"
                    )
                    * 100,
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "-q",
                        "tests/test_example.py",
                    ],
                    "sandbox": "docker",
                    "network": "disabled",
                    "workspace": "read_only",
                    "sandbox_profile": "test.offline.v1",
                    "sandbox_profile_version": 1,
                },
            ),
            _complete(
                work_id,
                index + 5,
                "dev_diff",
                "Inspected the final bounded diff.",
                observation={
                    "branch": "jarvis/work/c6-bench-dev-repair",
                    "diff": (
                        "diff --git a/src/jarvis/example.py b/src/jarvis/example.py\n"
                        "+def normalize(value):\n"
                        "+    cleaned = value.strip()\n"
                        "+    return cleaned\n"
                    )
                    * 80,
                    "truncated": False,
                },
            ),
            _complete(
                work_id,
                index + 6,
                "dev_status",
                "Checked isolated branch status after passing tests.",
                observation={
                    "prepared": True,
                    "branch": "jarvis/work/c6-bench-dev-repair",
                    "status": "## jarvis/work/c6-bench-dev-repair\n M src/jarvis/example.py\n",
                },
            ),
        )
    )
    return C6BenchmarkCase(
        case_id="development_repair_after_failure",
        rationale=(
            "Long engineering loop with broad reads/searches, a failed sandbox test, "
            "a corrective write, passing tests, diff and final status."
        ),
        request=_request(
            work_id=work_id,
            request_text=(
                "Correct the bounded normalization change safely, preserve the failing "
                "test evidence, and only create a local review commit after tests and "
                "diff inspection are satisfactory. If a local commit is the next safe "
                "step, use commit message exactly "
                "'test(c6): repair bounded normalization'."
            ),
            work_type=WorkType.DEVELOPMENT,
            steps=tuple(steps),
            actions=_development_actions(),
            assembler=assembler,
        ),
    )


def _development_commit_case(
    assembler: WorkContextAssembler,
) -> C6BenchmarkCase:
    work_id = "c6_bench_dev_commit"
    steps: list[WorkStep] = [
        _complete(
            work_id,
            1,
            "dev_prepare_workspace",
            "Prepared isolated worktree.",
            observation={
                "prepared": True,
                "branch": "jarvis/work/c6-bench-dev-commit",
                "base_revision": "b" * 40,
                "production_tree_modified": False,
            },
        )
    ]
    index = 2
    for number in range(10):
        steps.append(
            _complete(
                work_id,
                index,
                "dev_read_file",
                f"Reviewed implementation context {number}.",
                input_data={"path": f"src/jarvis/review_{number}.py"},
                observation={
                    "path": f"src/jarvis/review_{number}.py",
                    "text": (
                        f"class Review{number}:\n"
                        "    def evaluate(self, value):\n"
                        "        return value\n"
                    )
                    * 90,
                    "truncated": False,
                },
            )
        )
        index += 1
    for number in range(6):
        steps.append(
            _complete(
                work_id,
                index,
                "dev_search",
                f"Verified reference usage {number}.",
                input_data={"query": f"Review{number}"},
                observation={
                    "query": f"Review{number}",
                    "matches": [
                        {
                            "path": f"src/jarvis/review_{number}.py",
                            "line": 1,
                            "text": f"class Review{number}:",
                        }
                    ],
                },
            )
        )
        index += 1
    steps.extend(
        (
            _complete(
                work_id,
                index,
                "dev_write_file",
                "Applied the final reviewed source change.",
                input_data={
                    "path": "src/jarvis/review.py",
                    "text": (
                        "def accepted(value):\n"
                        "    # reviewed bounded acceptance implementation\n"
                        "    return bool(value)\n"
                    )
                    * 105,
                },
                observation={
                    "path": "src/jarvis/review.py",
                    "bytes_written": 45,
                    "production_tree_modified": False,
                },
            ),
            _complete(
                work_id,
                index + 1,
                "dev_run_tests",
                "Full bounded regression target passed.",
                input_data={"targets": ["tests/test_review.py"]},
                observation={
                    "passed": True,
                    "returncode": 0,
                    "timed_out": False,
                    "output": (
                        "tests/test_review.py::test_accepts_valid_value PASSED\n"
                        "tests/test_review.py::test_rejects_empty_value PASSED\n"
                    )
                    * 105,
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "-q",
                        "tests/test_review.py",
                    ],
                    "sandbox": "docker",
                    "network": "disabled",
                    "workspace": "read_only",
                    "sandbox_profile": "test.offline.v1",
                    "sandbox_profile_version": 1,
                },
            ),
            _complete(
                work_id,
                index + 2,
                "dev_diff",
                "Reviewed the final diff after passing tests.",
                observation={
                    "branch": "jarvis/work/c6-bench-dev-commit",
                    "diff": (
                        "diff --git a/src/jarvis/review.py b/src/jarvis/review.py\n"
                        "+def accepted(value):\n"
                        "+    return bool(value)\n"
                    )
                    * 90,
                    "truncated": False,
                },
            ),
            _complete(
                work_id,
                index + 3,
                "dev_status",
                "Confirmed only the reviewed source change remains uncommitted.",
                observation={
                    "prepared": True,
                    "branch": "jarvis/work/c6-bench-dev-commit",
                    "status": "## jarvis/work/c6-bench-dev-commit\n M src/jarvis/review.py\n",
                },
            ),
        )
    )
    return C6BenchmarkCase(
        case_id="development_ready_for_local_commit",
        rationale=(
            "Long review loop with passing tests, inspected diff and a single bounded "
            "uncommitted change; exercises whether context reduction preserves the "
            "evidence needed to select the final local commit."
        ),
        request=_request(
            work_id=work_id,
            request_text=(
                "Finish the reviewed change safely. Tests must remain passing and the "
                "diff/status must be inspected before creating a local review commit. "
                "Never push or merge. If a local commit is the next safe step, use "
                "commit message exactly 'test(c6): finalize reviewed change'."
            ),
            work_type=WorkType.DEVELOPMENT,
            steps=tuple(steps),
            actions=_development_actions(),
            assembler=assembler,
        ),
    )


def _research_finalize_case(
    assembler: WorkContextAssembler,
) -> C6BenchmarkCase:
    work_id = "c6_bench_research_finalize"
    steps: list[WorkStep] = [
        _complete(
            work_id,
            1,
            "acq_inspect_goal",
            "Inspected the exact owner capability goal.",
            observation={
                "goal": {
                    "goal_id": "goal-c6-benchmark",
                    "capability": "control a local display device safely",
                    "constraints": [
                        "prefer existing trusted technology",
                        "no broad network scanning",
                        "owner approval before activation",
                    ],
                }
            },
        )
    ]
    index = 2
    for number in range(12):
        steps.append(
            _complete(
                work_id,
                index,
                "research_web",
                f"Collected bounded authoritative evidence source {number}.",
                input_data={
                    "query": (
                        "official local device control protocol security architecture "
                        f"source {number}"
                    )
                },
                observation={
                    "provider": "benchmark",
                    "query": f"source-{number}",
                    "summary": (
                        "Authoritative documentation confirms the bounded capability "
                        "requirements, local-only targeting, rollback expectations, "
                        "and sandboxed verification constraints. "
                    )
                    * 70,
                    "evidence_refs": [f"evidence-{number}"],
                },
            )
        )
        index += 1

    steps.append(
        _complete(
            work_id,
            index,
            "acq_resolve",
            "Resolved the current candidate set after the latest evidence.",
            observation={
                "resolved": True,
                "selected_candidate_id": "candidate-custom-build",
                "candidate_count": 1,
                "blocked_candidate_count": 0,
            },
        )
    )

    return C6BenchmarkCase(
        case_id="research_ready_for_digest_bound_finalize",
        rationale=(
            "Long capability-research history whose deterministic resolution is current, "
            "so production control-plane bookkeeping is complete and the next step is a "
            "genuinely model-owned digest-bound acq_finalize decision."
        ),
        request=_request(
            work_id=work_id,
            request_text=(
                "The current deterministic acquisition resolution is up to date and "
                "selected the bounded custom-build path. Do not gather more evidence or "
                "re-resolve unless newer evidence exists. The next safe step is "
                "acq_finalize. Use exactly these parameters and no additional fields: "
                "proposed_capability_id='device.control'; "
                "proposed_package_id='device.control.custom'; "
                "proposed_package_version='1.0.0'; "
                "rollback_summary='Disable device.control.custom and restore the prior "
                "approved capability state.'; "
                "changed_paths=['src/jarvis/capabilities/device_control.py']; "
                "sandbox_profile_ids=['test.offline.v1']; "
                "verification_contract_ids=['device-control-contract-test']; "
                "development_test_targets=['tests/test_device_control.py']."
            ),
            work_type=WorkType.RESEARCH,
            steps=tuple(steps),
            actions=_research_actions(),
            assembler=assembler,
        ),
    )


def build_c6_benchmark_cases(
    *,
    assembler: WorkContextAssembler | None = None,
) -> tuple[C6BenchmarkCase, ...]:
    """Build the fixed three-case C6 quality-equivalence corpus."""

    context_assembler = assembler or WorkContextAssembler()
    return (
        _development_repair_case(context_assembler),
        _development_commit_case(context_assembler),
        _research_finalize_case(context_assembler),
    )
