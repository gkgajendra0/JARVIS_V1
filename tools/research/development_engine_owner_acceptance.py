"""Owner-machine architecture proof for the JARVIS DevelopmentEngine.

This harness is intentionally isolated from the real JARVIS repository. It creates a
temporary Git repository, lets the ChatGPT-plan/Codex DevelopmentEngine solve one tiny
engineering ticket through the real JARVIS governed development executors, runs tests
only through the approved Docker sandbox, and verifies that the source repository was
not mutated.

It consumes a small amount of the connected ChatGPT-plan allowance. It never pushes,
merges, activates a capability, or touches protected main.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict

from jarvis.chatgpt_plan import ChatGPTPlanSessionManager
from jarvis.development_engine import (
    CodexPlanDevelopmentEngine,
    DevelopmentDisposition,
    DevelopmentEngineCoordinator,
    DevelopmentSessionStore,
    DevelopmentTicketV1,
    WorkExecutorDevelopmentToolPort,
)
from jarvis.development_engine.codex import (
    OfficialCodexRuntimeFactory,
    REVIEWED_CODEX_SDK_VERSION,
)
from jarvis.work.development import (
    DevelopmentWorkspaceManager,
    DockerDevelopmentTestRunner,
    build_development_executors,
)
from jarvis.work.engine import WorkActionRegistry
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore


def _run(cwd: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _git(cwd: pathlib.Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git executable is unavailable")
    return _run(cwd, git, *args)


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        subprocess.run(
            [docker, "version"],
            capture_output=True,
            timeout=15,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _docker_image_available(image: str) -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", image],
            capture_output=True,
            timeout=20,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _preflight(*, model: str, test_image: str) -> dict[str, object]:
    """Check the owner-machine proof prerequisites without consuming model quota."""

    git_ready = shutil.which("git") is not None
    docker_ready = _docker_available()
    image_ready = docker_ready and _docker_image_available(test_image)
    plan = ChatGPTPlanSessionManager()
    chatgpt_plan_connected = plan.is_connected()
    model_catalog_error = None
    model_visible = False
    if chatgpt_plan_connected and model:
        try:
            model_visible = model in {item.slug for item in plan.list_models()}
        except Exception as exc:  # noqa: BLE001 - preflight reports provider readiness
            model_catalog_error = f"{type(exc).__name__}: {exc}"
    codex_version = None
    try:
        import openai_codex  # type: ignore

        codex_version = str(getattr(openai_codex, "__version__", "unknown"))
        codex_installed = True
    except ImportError:
        codex_installed = False

    checks = {
        "model_configured": bool(model),
        "test_image_configured": bool(test_image),
        "git_available": git_ready,
        "docker_available": docker_ready,
        "test_image_available": image_ready,
        "chatgpt_plan_connected": chatgpt_plan_connected,
        "development_model_visible": model_visible,
        "openai_codex_installed": codex_installed,
        "openai_codex_reviewed_version": (
            codex_version == REVIEWED_CODEX_SDK_VERSION
        ),
    }
    return {
        "schema": "jarvis.development_engine_owner_preflight.v1",
        "passed": all(checks.values()),
        "model": model,
        "test_image": test_image,
        "openai_codex_version": codex_version,
        "model_catalog_error": model_catalog_error,
        "checks": checks,
        "quota_consumed": False,
    }


def _prepare_disposable_repo(root: pathlib.Path) -> tuple[pathlib.Path, str]:
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "demo.py").write_text(
        "def answer() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_demo.py").write_text(
        "from src.demo import answer\n\n\ndef test_answer() -> None:\n"
        "    assert answer() == 42\n",
        encoding="utf-8",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "jarvis-acceptance@example.invalid")
    _git(repo, "config", "user.name", "JARVIS Acceptance")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD").casefold()


def _work_store(root: pathlib.Path) -> tuple[SQLiteWorkStore, WorkItem]:
    store = SQLiteWorkStore(root / "work.sqlite3")
    item = WorkItem(
        request="Repair the disposable demo so the approved test passes.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="development-engine-owner-acceptance",
        source_turn_id="proof",
    )
    store.create(item)
    running = store.save(
        item.transition(
            WorkState.RUNNING,
            status_detail="owner-machine development-engine proof",
        ),
        expected_version=item.version,
    )
    return store, running


async def _run_proof(
    *,
    model: str,
    test_image: str,
    output_path: pathlib.Path | None,
) -> dict[str, object]:
    if not _docker_available():
        raise RuntimeError(
            "Docker is unavailable. This proof refuses to execute model-edited code "
            "without the approved Docker sandbox."
        )
    if not _docker_image_available(test_image):
        raise RuntimeError(
            "The configured development test Docker image is unavailable locally. "
            "The proof will not consume model quota without its approved sandbox."
        )

    plan = ChatGPTPlanSessionManager()
    if not plan.is_connected():
        raise RuntimeError(
            "JARVIS is not connected to ChatGPT-plan usage. Run the existing "
            "ChatGPT-plan sign-in flow first."
        )
    visible_models = {item.slug for item in plan.list_models()}
    if model not in visible_models:
        raise RuntimeError(
            f"DevelopmentEngine model {model!r} is not visible to the connected "
            "ChatGPT-plan account."
        )

    try:
        import openai_codex  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "openai-codex is not installed. Install the JARVIS "
            "'development-codex' optional dependency before this proof."
        ) from exc
    codex_version = str(getattr(openai_codex, "__version__", "")).strip()
    if codex_version != REVIEWED_CODEX_SDK_VERSION:
        raise RuntimeError(
            "Owner proof requires reviewed openai-codex=="
            f"{REVIEWED_CODEX_SDK_VERSION}; found {codex_version or 'unknown'}."
        )

    with tempfile.TemporaryDirectory(prefix="jarvis-dev-engine-proof-") as temp:
        root = pathlib.Path(temp).resolve()
        repo, baseline_revision = _prepare_disposable_repo(root)
        work_store, work = _work_store(root)

        manager = DevelopmentWorkspaceManager(
            repository_root=repo,
            workspace_root=root / "worktrees",
        )
        runner = DockerDevelopmentTestRunner(test_image)
        actions = WorkActionRegistry(
            build_development_executors(manager, test_runner=runner)
        )
        ticket = DevelopmentTicketV1.create(
            request=(
                "Repair only src/demo.py so tests/test_demo.py passes. "
                "Do not modify tests. Inspect the repository as needed, make the "
                "smallest correct change, run the approved test, inspect the diff, "
                "and create the local candidate commit."
            ),
            work_id=work.work_id,
            engineering_change_id="acceptance_change",
            goal_id="acceptance_goal",
            goal_digest="a" * 64,
            architecture_artifact_id="acceptance_architecture",
            architecture_digest="b" * 64,
            base_revision=baseline_revision,
            workspace_id=work.work_id,
            required_operations=("development.proof",),
            repository_context_refs=("src/demo.py", "tests/test_demo.py"),
            writable_paths=("src/demo.py",),
            acceptance_criteria=("pytest:tests/test_demo.py",),
            allowed_tools=(
                "prepare_workspace",
                "list_files",
                "read_file",
                "search_source",
                "write_file",
                "run_tests",
                "inspect_diff",
                "commit_candidate",
                "status",
            ),
        )
        tool_resources = ResourceLeaseManager({"git": 1, "cpu": 1})
        tools = WorkExecutorDevelopmentToolPort(
            ticket=ticket,
            store=work_store,
            actions=actions,
            resources=tool_resources,
        )
        sessions = DevelopmentSessionStore(work_store)
        engine = CodexPlanDevelopmentEngine(
            chatgpt_plan=plan,
            model=model,
            sessions=sessions,
            state_dir=root / "codex",
        )
        coordinator = DevelopmentEngineCoordinator(
            engine=engine,
            sessions=sessions,
            resources=ResourceLeaseManager({"development_intelligence": 1}),
            resource_keys=("development_intelligence",),
        )

        first = await coordinator.execute(
            ticket,
            tools=tools,
            evidence_refs=("owner-machine-proof",),
        )
        second = await coordinator.execute(
            ticket,
            tools=tools,
            evidence_refs=("owner-machine-proof",),
        )

        session = sessions.get(ticket.digest)
        thread_id = None if session is None else session.thread_id
        thread_resumed_after_runtime_restart = False
        if thread_id:
            restarted_runtime = OfficialCodexRuntimeFactory().create(
                access_token=plan.access_token(),
                codex_home=(root / "codex" / "home"),
                cwd=(root / "codex" / "scratch" / ticket.ticket_id),
            )
            try:
                resumed_thread = await restarted_runtime.resume_thread(
                    thread_id,
                    model=model,
                )
                thread_resumed_after_runtime_restart = resumed_thread.id == thread_id
            finally:
                await restarted_runtime.close()

        source_after = _git(repo, "rev-parse", "HEAD").casefold()
        source_status = _git(repo, "status", "--porcelain=v1")
        progress = dict(tools.snapshot())
        result = first.result
        candidate = result.candidate_revision
        candidate_file = None
        if candidate:
            candidate_file = _git(repo, "show", f"{candidate}:src/demo.py")

        checks = {
            "completed": result.disposition is DevelopmentDisposition.COMPLETED,
            "candidate_revision_present": bool(candidate),
            "source_revision_unchanged": source_after == baseline_revision,
            "source_tree_clean": not source_status,
            "only_approved_path_changed": result.changed_files == ("src/demo.py",),
            "test_evidence_present": bool(result.test_evidence_refs),
            "candidate_contains_expected_fix": (
                candidate_file is not None and "return 42" in candidate_file
            ),
            "identical_reasoning_reused": second.reused is True,
            "identical_result_reused": second.result.digest == result.digest,
            "thread_recorded": bool(thread_id),
            "thread_resumed_after_runtime_restart": (
                thread_resumed_after_runtime_restart
            ),
        }
        passed = all(checks.values())

        usage_payload = None if result.usage is None else asdict(result.usage)
        model_turns = 0 if result.usage is None else result.usage.model_turns
        tool_calls = 0 if result.usage is None else result.usage.tool_calls
        input_tokens = 0 if result.usage is None else result.usage.input_tokens
        cached_tokens = 0 if result.usage is None else result.usage.cached_input_tokens
        efficiency = {
            "provider_model_turns": model_turns,
            "governed_tool_calls": tool_calls,
            "tool_calls_per_model_turn": (
                0.0 if model_turns == 0 else round(tool_calls / model_turns, 3)
            ),
            "cached_input_ratio": (
                0.0 if input_tokens == 0 else round(cached_tokens / input_tokens, 4)
            ),
            "identical_second_execution_reused_without_cloud_turn": second.reused,
        }

        report: dict[str, object] = {
            "schema": "jarvis.development_engine_owner_acceptance.v1",
            "passed": passed,
            "model": model,
            "openai_codex_version": codex_version,
            "baseline_revision": baseline_revision,
            "source_revision_after": source_after,
            "ticket_id": ticket.ticket_id,
            "ticket_digest": ticket.digest,
            "result_id": result.result_id,
            "result_digest": result.digest,
            "disposition": result.disposition.value,
            "candidate_revision": candidate,
            "changed_files": list(result.changed_files),
            "test_evidence_refs": list(result.test_evidence_refs),
            "usage": usage_payload,
            "efficiency": efficiency,
            "reasoning_fingerprint": first.reasoning_fingerprint,
            "second_execution_reused": second.reused,
            "provider_thread_id": thread_id,
            "provider_runtime_restart_resume_verified": (
                thread_resumed_after_runtime_restart
            ),
            "cloud_engine_invocations_expected": 1,
            "progress": progress,
            "checks": checks,
        }

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8",
            )

        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the isolated JARVIS DevelopmentEngine owner-machine proof."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("JARVIS_DEVELOPMENT_ENGINE_MODEL")
        or os.environ.get("JARVIS_CHATGPT_PLAN_MODEL"),
        help="ChatGPT-plan model to use for the Codex engineering thread.",
    )
    parser.add_argument(
        "--test-image",
        default=os.environ.get("JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE"),
        help="Approved JARVIS development test Docker image.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Check Git, Docker, test image, ChatGPT-plan connection and Codex SDK "
            "without consuming model quota."
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    model = str(args.model or "").strip()
    test_image = str(args.test_image or "").strip()
    if not model:
        print(
            "ERROR: --model or JARVIS_DEVELOPMENT_ENGINE_MODEL is required.",
            file=sys.stderr,
        )
        return 2
    if not test_image:
        print(
            "ERROR: --test-image or JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE is required.",
            file=sys.stderr,
        )
        return 2

    preflight = _preflight(model=model, test_image=test_image)
    if args.preflight_only:
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0 if preflight["passed"] is True else 1
    if preflight["passed"] is not True:
        print(json.dumps(preflight, indent=2, sort_keys=True), file=sys.stderr)
        return 1

    try:
        report = asyncio.run(
            _run_proof(
                model=model,
                test_image=test_image,
                output_path=args.output,
            )
        )
    except Exception as exc:  # noqa: BLE001 - acceptance boundary reports exact failure
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
