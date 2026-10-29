"""Explicit, isolated scripted voice smoke; never the normal voice entry point."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings


@contextmanager
def smoke_environment(profile: Path):
    root = profile.resolve().parent
    values = {
        "JARVIS_MACHINE_CONFIG": str(profile.resolve()),
        "JARVIS_RUNTIME_ENV_OVERRIDES": "false",
        "JARVIS_AUTHORITY_AUDIT_DB": str(root / "authority.sqlite3"),
        "JARVIS_DEPLOYMENT_ROOT": str(root / "deployment"),
        "JARVIS_RELEASES_ROOT": str(root / "releases"),
        "XDG_STATE_HOME": str(root / "state"),
    }
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepare_smoke_profile(source: Path, lab: Path, *, tool_paths) -> Path:
    source = source.resolve(strict=True)
    lab = lab.resolve()
    if lab == source.parent or source.parent.is_relative_to(lab):
        raise ValueError("Smoke profile must be separate from the original profile")
    settings = load_machine_settings(source)
    settings.update({key: str(value) for key, value in tool_paths.items()})
    lab.mkdir(parents=True, exist_ok=False)
    profile = lab / "machine.json"
    save_machine_settings(settings, profile)
    return profile


def smoke_config(config: JarvisConfig) -> JarvisConfig:
    if config.ai_provider != "gemini":
        raise ValueError("Scripted smoke requires the configured Gemini provider")
    return replace(
        config,
        personal_context_mode="apply",
        personal_learning_mode="off",
        personal_learning_reenable_categories=(),
        memory_enabled=True,
        memory_candidate_extraction_enabled=False,
        memory_semantic_recall_model=None,
        work_orchestration_enabled=False,
        github_promotion_enabled=False,
        show_transcript=False,
        chatgpt_plan_enabled=False,
        vision_enabled=False,
        speaker_shadow_enabled=False,
        active_speaker_shadow_enabled=False,
        pocket3_native_tracking_enabled=False,
        gemini_fallback=replace(config.gemini_fallback, enabled=True),
    )


async def run_smoke_runtime(config, *, model: str, runtime_builder=None):
    """Run normal voice transport with an explicit grant and transient observer.

    Private controller fields are read only here in the lab adapter; production
    entry points never import this module or install its factory.
    """
    import asyncio
    from uuid import uuid4

    from jarvis.hands.provider_adapters import RoutedStructuredOutputClient
    from jarvis.voice.semantic_script_smoke import build_smoke_session_components

    if not isinstance(model, str) or not model.strip():
        raise ValueError("An explicit routed semantic model is required")
    config = smoke_config(config)
    if runtime_builder is None:
        from jarvis.voice.production_runtime import build_production_voice_runtime

        runtime_builder = build_production_voice_runtime
    grant = None

    def factory(conversation):
        return build_smoke_session_components(
            conversation,
            authority=runtime._capability_runtime.personal_learning_authority,
            grant=grant,
            client=RoutedStructuredOutputClient(
                routing_runtime=runtime._routing_runtime,
                role="memory.extraction",
                model=model.strip(),
                max_output_tokens=1024,
                free_output_tokens=1024,
            ),
            accepted_plan_epoch=runtime._memory_runtime.accepted_plan_epoch,
        )

    runtime = runtime_builder(config, semantic_session_factory=factory)
    completed = False
    try:
        grant = await asyncio.to_thread(
            runtime._capability_runtime.open_personal_learning,
            "semantic-script-smoke-" + uuid4().hex,
            "gemini",
        )
        await runtime.run()
        completed = True
    finally:
        if grant is not None:
            runtime._capability_runtime.close_personal_learning(grant)
        if not completed and not getattr(runtime._memory_runtime, "_closed", False):
            # Hello denial or failure before the controller's cleanup boundary.
            from contextlib import AsyncExitStack

            async with AsyncExitStack() as cleanup:
                cleanup.callback(runtime._capability_runtime.close)
                cleanup.push_async_callback(runtime._routing_runtime.aclose)
                if runtime._research_service is not None:
                    cleanup.push_async_callback(runtime._research_service.close)
                cleanup.push_async_callback(runtime._memory_runtime.close)


def main():
    import argparse
    import asyncio

    from jarvis.authority.tooling import (
        resolve_opa_binary,
        resolve_windows_hello_helper,
    )
    from jarvis.logging_config import configure_logging
    from jarvis.machine_config import default_machine_config_path
    from jarvis.preflight import require_startup_preflight
    from jarvis.voice.semantic_script_smoke import SMOKE_UTTERANCES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=default_machine_config_path())
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Real voice smoke requires Windows, SQLCipher, DPAPI and Hello")
    if not args.model.strip():
        parser.error("An explicit semantic model is required")
    settings = load_machine_settings(args.profile)
    tool_paths = {
        "JARVIS_OPA_PATH": resolve_opa_binary(machine_settings=settings).resolve(),
        "JARVIS_WINDOWS_HELLO_HELPER": resolve_windows_hello_helper(
            machine_settings=settings
        ).resolve(),
    }
    profile = prepare_smoke_profile(args.profile, args.lab_root, tool_paths=tool_paths)
    with smoke_environment(profile):
        config = smoke_config(JarvisConfig.from_environment())
        configure_logging(config.log_level, jsonl_path=profile.parent / "smoke.jsonl")
        require_startup_preflight(config)
        print("Scripted transient observation only; no checkpoint writes or resume.")
        print(
            "Normal Gemini Live audio is still sent to Gemini. Use synthetic speech only."
        )
        print(f"Test profile: {profile}")
        print("After Hello approval, wake Jarvis and say each line separately:")
        for utterance in SMOKE_UTTERANCES:
            print(f"  {utterance}")
        print("Ctrl+C stops the lab. A new wake starts with empty semantic state.")
        asyncio.run(run_smoke_runtime(config, model=args.model))


if __name__ == "__main__":
    main()
