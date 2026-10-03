"""Non-destructive preflight for a real Phase-9 external capability mission."""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.chatgpt_plan import ChatGPTPlanSessionManager
from jarvis.config import JarvisConfig
from jarvis.engineering_substrate.secrets.store import (
    SecretNotFoundError,
    SecretStore,
)
from jarvis.machine_config import load_machine_settings
from jarvis.model_routing.invoker import build_default_model_adapter_registry
from jarvis.model_routing.router import build_default_work_targets


class Phase9MissionPreflightError(RuntimeError):
    """A required owner-machine prerequisite is not ready."""


@dataclass(frozen=True, slots=True)
class RepositoryState:
    head_sha: str
    tracked_dirty: bool


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        shell=False,
    )
    return completed.stdout.strip()


def _repo_state(repo: pathlib.Path) -> RepositoryState:
    head = _git(repo, "rev-parse", "HEAD").casefold()
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    return RepositoryState(head_sha=head, tracked_dirty=bool(status))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase9MissionPreflightError(message)


def run_preflight(
    *,
    repo_root: pathlib.Path,
    expected_commit: str | None = None,
) -> dict[str, object]:
    _require(
        sys.platform == "win32", "real external mission preflight requires Windows"
    )

    repo = pathlib.Path(repo_root).resolve()
    _require(
        repo.is_dir() and not repo.is_symlink(), "repo root must be a real directory"
    )
    state = _repo_state(repo)
    _require(not state.tracked_dirty, "tracked working tree must be clean")

    expected = (
        None if expected_commit is None else str(expected_commit).strip().casefold()
    )
    if expected:
        _require(
            state.head_sha == expected, "repository HEAD does not match expected commit"
        )

    config = JarvisConfig.from_environment()
    _require(config.chatgpt_plan_enabled, "ChatGPT-plan reasoning is not enabled")
    _require(bool(config.chatgpt_plan_model), "ChatGPT-plan model is not configured")
    _require(
        config.development_engine_enabled,
        "governed DevelopmentEngine capability development is disabled",
    )
    development_model = str(
        config.development_engine_model or config.chatgpt_plan_model or ""
    ).strip()
    _require(
        bool(development_model), "DevelopmentEngine coding model is not configured"
    )
    _require(
        config.work_orchestration_enabled, "durable Work orchestration is disabled"
    )
    _require(config.github_promotion_enabled, "governed GitHub promotion is disabled")

    manager = ChatGPTPlanSessionManager()
    _require(manager.is_connected(), "ChatGPT-plan OAuth is not connected")
    models = manager.list_models()
    visible_models = {item.slug for item in models}
    _require(
        str(config.chatgpt_plan_model) in visible_models,
        "configured ChatGPT-plan model is not visible to the connected account",
    )
    _require(
        development_model in visible_models,
        "configured DevelopmentEngine model is not visible to the connected account",
    )

    try:
        codex_module = importlib.import_module("openai_codex")
    except ImportError as exc:
        raise Phase9MissionPreflightError(
            "openai-codex is not installed; install the JARVIS development-codex "
            "optional dependency before the real capability mission"
        ) from exc
    codex_version = str(getattr(codex_module, "__version__", "")).strip()
    _require(
        codex_version == "0.160.0",
        "owner machine does not have the reviewed openai-codex==0.160.0 runtime",
    )

    docker = shutil.which("docker")
    _require(bool(docker), "Docker is unavailable for governed development testing")
    test_image = str(config.development_test_docker_image or "").strip()
    _require(bool(test_image), "development test Docker image is not configured")
    image_probe = subprocess.run(
        [str(docker), "image", "inspect", test_image],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        check=False,
        shell=False,
    )
    _require(
        image_probe.returncode == 0,
        "configured development test Docker image is unavailable locally",
    )

    adapters = build_default_model_adapter_registry(
        chatgpt_plan_session_manager=manager,
    )
    targets = build_default_work_targets(
        configured_provider=config.ai_provider,
        configured_model=config.work_orchestration_model,
        adapter_registry=adapters,
        chatgpt_plan_enabled=True,
        chatgpt_plan_model=config.chatgpt_plan_model,
    )
    all_targets = targets.registry.all()
    _require(
        targets.primary_target_id == "work.chatgpt_plan.default",
        "ChatGPT-plan target is not the durable Work primary",
    )
    _require(
        all(target.locality.value != "local" for target in all_targets),
        "production Work pool still contains a local LLM",
    )
    _require(
        len(all_targets) == 1 and all_targets[0].provider_id == "chatgpt_plan",
        "production Work pool must not contain an automatic paid-provider fallback",
    )

    _require(
        bool(config.github_app_secret_id),
        "GitHub promotion secret ID is not configured",
    )
    secret_store = SecretStore()
    try:
        descriptor = secret_store.verified_descriptor(str(config.github_app_secret_id))
    except SecretNotFoundError as exc:
        raise Phase9MissionPreflightError(
            "configured GitHub promotion secret is missing"
        ) from exc
    _require(
        descriptor.lifecycle_state.value == "active",
        "configured GitHub promotion secret is not active",
    )

    machine = load_machine_settings()
    uv_path = str(machine.get("JARVIS_UV_EXECUTABLE_PATH") or "").strip()
    uv_sha = str(machine.get("JARVIS_UV_EXECUTABLE_SHA256") or "").strip()
    _require(bool(uv_path), "reviewed uv executable path is not configured")
    _require(bool(uv_sha), "reviewed uv executable SHA-256 is not configured")

    return {
        "status": "PASS",
        "repo_head": state.head_sha,
        "chatgpt_plan_connected": True,
        "chatgpt_plan_model": config.chatgpt_plan_model,
        "work_primary": targets.primary_target_id,
        "work_targets": [target.target_id for target in all_targets],
        "local_llm_in_work_pool": False,
        "global_brain_router_mode": config.global_brain_router_mode,
        "work_orchestration_enabled": config.work_orchestration_enabled,
        "development_engine_enabled": config.development_engine_enabled,
        "development_engine_model": development_model,
        "openai_codex_version": codex_version,
        "development_test_image": test_image,
        "work_context_mode": config.work_context_mode,
        "automatic_paid_fallback": False,
        "github_promotion_enabled": config.github_promotion_enabled,
        "github_repository": config.github_repository_full_name,
        "github_secret_descriptor_verified": True,
        "reviewed_uv_configured": True,
        "realtime_provider": config.ai_provider,
        "realtime_model": (
            config.gemini_realtime_model
            if config.ai_provider == "gemini"
            else config.realtime_model
        ),
        "next": (
            "start the JARVIS runtime and submit one natural external outcome; "
            "do not provide protocol/IP/SDK implementation hints"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phase9-external-mission-preflight",
        description="Validate owner-machine prerequisites for a real Phase-9 mission.",
    )
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    parser.add_argument("--expected-commit", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_preflight(
            repo_root=args.repo_root,
            expected_commit=args.expected_commit,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        Phase9MissionPreflightError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
