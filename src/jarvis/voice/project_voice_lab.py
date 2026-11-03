"""Isolated Windows VOICE lab for project conversation memory (opt-in).

Runs the normal production voice runtime (wake word, barge-in, Gemini Live,
tools) against an isolated, exact-source project-memory lab profile. The lab
root is shared with ``jarvis.voice.project_memory_lab`` at the same commit, so
/projects, /inspect and /forget can be checked in the text lab between voice
runs (never at the same time: both take the lab's OS lock).

Production memory is never opened or copied: startup refuses unless the memory
database resolves inside the lab. Paid fallback is disabled. ``--baseline``
runs the identical runtime with project memory off, for latency/token
comparison in ``voice-usage.jsonl``.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

# The ONLY tools Gemini can see or call in each lab mode, enforced in code by
# VoiceRuntimeController (restrict_tools). Hands, desktop/file control,
# capability acquisition, research, work, vision and canonical-memory tools are
# all withheld; their internal authority services still run for Hello/SQLCipher.
BASELINE_TOOLS = frozenset({"enter_standby"})
# Project memory's own tools: context, older-history search and forgetting.
PROJECT_TOOLS = frozenset(
    {"prepare_project_turn", "search_project_history", "forget_saved_history"}
)
PROJECT_MEMORY_TOOLS = frozenset({"enter_standby"}) | PROJECT_TOOLS


def lab_tool_allowlist(*, baseline: bool) -> frozenset[str]:
    return BASELINE_TOOLS if baseline else PROJECT_MEMORY_TOOLS


def voice_lab_config(config):
    if config.ai_provider != "gemini":
        raise ValueError("existing Gemini configuration required")
    return replace(
        config,
        memory_enabled=True,
        personal_context_mode="off",
        personal_learning_mode="off",
        personal_learning_reenable_categories=(),
        memory_candidate_extraction_enabled=False,
        memory_semantic_recall_model=None,
        work_orchestration_enabled=False,
        github_promotion_enabled=False,
        chatgpt_plan_enabled=False,
        show_transcript=False,
        vision_enabled=False,
        speaker_shadow_enabled=False,
        active_speaker_shadow_enabled=False,
        pocket3_native_tracking_enabled=False,
        # Free credential lane only: the isolated lab never spends paid budget.
        gemini_fallback=replace(config.gemini_fallback, enabled=False),
    )


def require_isolated_memory(lab: Path) -> Path:
    from jarvis.memory.runtime import default_memory_database_path

    database = default_memory_database_path().resolve()
    if database.parent != lab.resolve():
        raise RuntimeError("memory database is not inside the isolated lab; refusing")
    return database


def project_memory_factory(
    memory_runtime, capability_runtime, diagnostics=None, *, fast_path=True
):
    from jarvis.voice.project_memory_lab import standard_history_source
    from jarvis.voice.project_voice import VoiceProjectMemory

    return VoiceProjectMemory(
        memory_runtime,
        capability_runtime,
        source_clearance=standard_history_source,
        diagnostics=diagnostics,
        fast_path=fast_path,
    )


async def run_voice_lab(
    config,
    lab: Path,
    *,
    baseline: bool,
    runtime_builder=None,
    diagnostics=None,
    fast_path: bool = True,
):
    """``diagnostics`` (VoiceDiagnostics) only with explicit --record-diagnostics.

    ``fast_path=False`` (--tool-only-memory) keeps the earlier behaviour: every
    request goes through prepare_project_turn. For A/B latency comparisons.
    """
    from dataclasses import replace

    from jarvis.voice.voice_usage_meter import VoiceUsageMeter

    # The lab decides memory itself: a production flag in the machine profile
    # must never add project memory to a -Baseline run.
    if getattr(config, "project_memory_mode", "off") != "off":
        config = replace(config, project_memory_mode="off")

    if runtime_builder is None:
        from jarvis.voice.production_runtime import build_production_voice_runtime

        runtime_builder = build_production_voice_runtime
    allowlist = lab_tool_allowlist(baseline=baseline)
    meter = VoiceUsageMeter(
        lab / "voice-usage.jsonl",
        mode="baseline"
        if baseline
        else "project_memory"
        if fast_path
        else "project_memory_tool_only",
        allowed_tools=allowlist,
    )

    def observe_session(session, bridge):
        meter.attach(session, bridge)
        if diagnostics is not None:
            diagnostics.attach(session, bridge)

    def memory_factory(memory_runtime, capability_runtime):
        return project_memory_factory(
            memory_runtime,
            capability_runtime,
            diagnostics=diagnostics,
            fast_path=fast_path,
        )

    runtime = runtime_builder(
        config,
        voice_session_observer=observe_session,
        tool_allowlist=allowlist,
        **({} if baseline else {"project_memory_factory": memory_factory}),
        **(
            {"session_audio_tap": diagnostics.audio_tap}
            if diagnostics is not None
            else {}
        ),
    )
    try:
        await runtime.run()
    finally:
        if diagnostics is not None:
            await diagnostics.aclose()
    return runtime


def main():
    import argparse
    import asyncio
    import msvcrt

    from jarvis.authority.tooling import (
        resolve_opa_binary,
        resolve_windows_hello_helper,
    )
    from jarvis.config import JarvisConfig
    from jarvis.logging_config import configure_logging
    from jarvis.machine_config import default_machine_config_path, load_machine_settings
    from jarvis.preflight import require_startup_preflight
    from jarvis.voice.project_memory_lab import (
        prepare_project_profile,
        project_lab_environment,
        verify_source,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=default_machine_config_path())
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--resume-lab", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument(
        "--tool-only-memory",
        action="store_true",
        help="Project memory without the session preload: every request calls "
        "prepare_project_turn (the earlier behaviour, for A/B comparison).",
    )
    parser.add_argument(
        "--record-diagnostics",
        action="store_true",
        help="Lab only: keep DPAPI-sealed utterance audio and per-turn records "
        "in this lab (7-day / 5-run retention).",
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires Windows audio, SQLCipher, DPAPI and Hello")
    repo = Path(__file__).resolve().parents[3]
    verify_source(repo, args.source_commit)
    settings = load_machine_settings(args.profile)
    tool_paths = (
        {}
        if args.resume_lab
        else {
            "JARVIS_OPA_PATH": resolve_opa_binary(machine_settings=settings).resolve(),
            "JARVIS_WINDOWS_HELLO_HELPER": resolve_windows_hello_helper(
                machine_settings=settings
            ).resolve(),
        }
    )
    profile = prepare_project_profile(
        args.profile,
        args.lab_root,
        resume=args.resume_lab,
        commit=args.source_commit,
        tool_paths=tool_paths,
    )
    lab = profile.parent
    with project_lab_environment(profile, repo):
        database = require_isolated_memory(lab)
        lock = (lab / "project-memory.lock").open("a+b")
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock.close()
            parser.error("another lab process owns this lab; close it first")
        try:
            config = voice_lab_config(JarvisConfig.from_environment())
            configure_logging(config.log_level, jsonl_path=lab / "voice-lab.jsonl")
            require_startup_preflight(config)
            mode = (
                "BASELINE (project memory off)" if args.baseline else "PROJECT MEMORY"
            )
            print(f"VOICE LAB {mode}. Isolated memory: {database}")
            print(
                "Tools Gemini can call: "
                + ", ".join(sorted(lab_tool_allowlist(baseline=args.baseline)))
                + ". Hands, desktop/file control, capability acquisition, research and work are unavailable."
            )
            print(
                "Normal wake word, barge-in and Gemini Live. Free lane only; no Paid fallback."
            )
            if not args.baseline:
                print(
                    "Approve Windows Hello for project history. Then wake Jarvis and talk."
                )
                print(
                    "Use the text lab on this same lab root (-ResumeLab) for /projects, /inspect and /forget, after Ctrl+C here."
                )
            print(
                "Measurements: "
                + str(lab / "voice-usage.jsonl")
                + ". Ctrl+C stops voice."
            )
            diagnostics = None
            if args.record_diagnostics:
                from jarvis.security.dpapi import WindowsDpapiKeyProtector
                from jarvis.voice.voice_diagnostics import VoiceDiagnostics

                diagnostics = VoiceDiagnostics(
                    lab, protector=WindowsDpapiKeyProtector()
                )
                print(
                    "DIAGNOSTICS ON: your post-wake microphone audio and per-turn records are "
                    f"kept DPAPI-encrypted in {diagnostics.run_dir} (7 days, last 5 runs). "
                    "Nothing is uploaded beyond normal Gemini Live audio. After Ctrl+C, "
                    "run this launcher again with -DiagnosticsReport."
                )
            asyncio.run(
                run_voice_lab(
                    config,
                    lab,
                    baseline=args.baseline,
                    diagnostics=diagnostics,
                    fast_path=not args.tool_only_memory,
                )
            )
            if diagnostics is not None:
                print(
                    "Report: python -m jarvis.voice.voice_diagnostics report --lab-root "
                    + str(lab)
                )
        except KeyboardInterrupt:
            print("Voice lab stopped.")
        finally:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                lock.close()


if __name__ == "__main__":
    main()
