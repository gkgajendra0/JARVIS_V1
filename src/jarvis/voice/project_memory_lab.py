"""Exact-source, isolated Windows TEXT acceptance for project memory.

No microphone or paid fallback is enabled. Native STT/TTS qualification is a
separate blocked gate. Existing Gemini free credentials, SQLCipher/DPAPI, OPA and
Windows Hello are reused; original machine settings are not edited.
"""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

from jarvis.conversation import ConversationTurn
from jarvis.memory.explicit import MemorySecretRejectedError, reject_prohibited_secret
from jarvis.memory.topic_continuity_policy import _RESTRICTED
from jarvis.voice.semantic_smoke_lab import prepare_smoke_profile, smoke_environment

MARKER = "jarvis-project-memory-text-v1"


@contextmanager
def project_lab_environment(profile: Path, repo: Path):
    """Use this exact-source candidate's policy only within the isolated lab."""
    policy = (repo / "policies" / "step3_authority.rego").resolve(strict=True)
    previous = os.environ.get("JARVIS_STEP3_POLICY_PATH")
    with smoke_environment(profile):
        os.environ["JARVIS_STEP3_POLICY_PATH"] = str(policy)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("JARVIS_STEP3_POLICY_PATH", None)
            else:
                os.environ["JARVIS_STEP3_POLICY_PATH"] = previous


def standard_history_source(turn):
    if (
        not isinstance(turn, ConversationTurn)
        or len(turn.text.encode("utf-8")) > 8000
        or _RESTRICTED.search(turn.text)
    ):
        return False
    try:
        reject_prohibited_secret(predicate="", value=turn.text)
    except MemorySecretRejectedError:
        return False
    return True


def verify_source(repo: Path, expected: str):
    if len(expected) != 40 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("exact commit required")
    try:
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("exact clean source unavailable") from exc
    if head != expected or dirty:
        raise ValueError("exact clean source required")
    return head


def prepare_project_profile(
    source: Path, lab: Path, *, resume: bool, commit=None, tool_paths=None
):
    source = source.resolve(strict=True)
    lab = lab.resolve()
    if lab == source.parent or source.parent.is_relative_to(lab):
        raise ValueError("profile must be isolated")
    marker = lab / "project-memory.marker"
    if resume:
        if not marker.is_file() or marker.read_text() != json.dumps(
            {"kind": MARKER, "commit": commit}, sort_keys=True
        ):
            raise ValueError("only this exact-source marked lab can resume")
        profile = (lab / "machine.json").resolve(strict=True)
        if profile.parent != lab:
            raise ValueError("profile escaped isolated root")
        return profile
    profile = prepare_smoke_profile(source, lab, tool_paths=tool_paths or {})
    marker.write_text(json.dumps({"kind": MARKER, "commit": commit}, sort_keys=True))
    return profile


def build_project_personal_session(conversation, memory, capability):
    from jarvis.voice.personal_context import PersonalContextSession

    return PersonalContextSession(
        conversation=conversation,
        retrieval=memory.retrieval,
        authority=capability,
        retire=lambda: None,
        explicit_question_queries=True,
    )


async def run_text_lab(config, root: Path, *, model: str):
    import asyncio
    import msvcrt
    from uuid import uuid4

    from jarvis.authority.conversation_history import ConversationHistoryAuthority
    from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.hands.provider_adapters import RoutedStructuredOutputClient
    from jarvis.memory.project_access import ProjectArchiveAccess
    from jarvis.memory.project_controls import ProjectControls
    from jarvis.memory.runtime import build_default_memory_runtime
    from jarvis.model_routing.runtime import build_routing_runtime
    from jarvis.voice.project_answer_provider import ProjectAnswerProvider
    from jarvis.voice.project_conversation import ProjectConversationCoordinator
    from jarvis.work.privacy import build_default_work_payload_codec
    from jarvis.work.store import SQLiteWorkStore

    # OS-backed lock survives crashes without leaving a stale PID lease.
    lock = (root / "project-memory.lock").open("a+b")
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError("another process owns this lab") from None
    memory = build_default_memory_runtime(root / "memory.db")
    broker = CapabilityAuthorityBroker()
    capability = CapabilityRuntime(
        executors=(), resolver=CapabilityResolver((), builtins=()), authority=broker
    )
    authority = ConversationHistoryAuthority(broker)
    routing = None
    work_store = None
    coordinator = None
    try:
        await memory.start()
        grant = await asyncio.to_thread(authority.open, str(uuid4()), "gemini")
        memory.bind_conversation_history_authority(authority)
        access = ProjectArchiveAccess(
            memory.project_conversations, authority=authority, grant=grant
        )
        # Isolated counters must never reset the owner's cumulative paid budget.
        # Disable paid targets for this lab, rather than granting a new allowance.
        path = root / "routing.sqlite3"
        work_store = SQLiteWorkStore(
            path, payload_codec=build_default_work_payload_codec(path)
        )
        routing = build_routing_runtime(
            work_store=work_store,
            provider="gemini",
            model=model,
            config=replace(config.gemini_fallback, enabled=False),
        )
        client = RoutedStructuredOutputClient(
            routing_runtime=routing,
            role="memory.recall",
            model=model,
            max_output_tokens=2048,
            free_output_tokens=2048,
        )
        provider = ProjectAnswerProvider(client)

        def personal(conversation):
            return build_project_personal_session(conversation, memory, capability)

        coordinator = ProjectConversationCoordinator(
            access, source_clearance=standard_history_source, personal_factory=personal
        )
        controls = ProjectControls(access)
        print(
            "TEXT LAB: original history retained locally when eligible. Configured Free credential lane only; no Paid fallback. Windows Hello grants project retention; personal reads/deletion keep their own approvals."
        )
        print(
            "Commands: /projects /inspect /pause /resume /forget /sleep /quit. Normal text selects explicit projects and asks questions."
        )
        while True:
            text = await asyncio.to_thread(input, "Jarvis> ")
            if text == "/quit":
                break
            if not text.strip():
                continue
            try:
                if text == "/sleep":
                    coordinator.invalidate("sleep")
                    print("Listening segment closed; project selection retained.")
                    continue
                if text.startswith("/"):
                    catalog = await access.catalog()
                    if text == "/projects":
                        print(
                            json.dumps(asdict(catalog), default=str, ensure_ascii=False)
                        )
                        continue
                    if catalog.current is None:
                        raise ValueError("no active project")
                    project_id = catalog.current.project_id
                    if text == "/inspect":
                        print(
                            json.dumps(
                                asdict(await controls.inspect_project(project_id)),
                                default=str,
                                ensure_ascii=False,
                            )
                        )
                        continue
                    if text in {"/pause", "/resume"}:
                        coordinator.invalidate("retention_change")
                        await controls.pause_project(
                            project_id, paused=text == "/pause"
                        )
                        print("Retention setting committed.")
                        continue
                    if text == "/forget":
                        inspected = await controls.inspect_project(project_id)
                        coordinator.invalidate("forget")
                        result = await controls.forget_project(
                            project_id, expected_revision=inspected.archive_revision
                        )
                        print(json.dumps(asdict(result)))
                        continue
                    raise ValueError("unknown command")
                conversation = ConversationSession()
                conversation.start()
                turn = conversation.accept_turn(ConversationRole.USER, text)
                result = await coordinator.respond(
                    conversation, turn, provider=provider, authorize=access.current
                )
                await coordinator.validate_for_release(result)
                if not coordinator.validate_current(result.packet):
                    raise PermissionError("answer invalidated")
                print(result.announcement)
                print(result.answer)
                receipt = await coordinator.record_assistant(
                    conversation, result, delivered_text=result.answer
                )
                print(
                    json.dumps(
                        {
                            "request_id": result.packet.request_id,
                            "context_revision": result.packet.revision,
                            "user_receipt": asdict(result.receipt),
                            "assistant_receipt": asdict(receipt),
                            "usage": result.usage,
                        }
                    )
                )
            except (PermissionError, ValueError, RuntimeError, OSError) as exc:
                print(
                    f"NOT COMPLETED: {json.dumps(coordinator.diagnostics())}; error={type(exc).__name__}. Inspect saved sources before retrying; no successful-save claim for failed stage."
                )
    finally:
        if coordinator is not None:
            coordinator.invalidate("shutdown")
        authority.close()
        capability.close()
        if routing is not None:
            await routing.aclose()
        await memory.close()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def main():
    import argparse
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.machine_config import default_machine_config_path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=default_machine_config_path())
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--resume-lab", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error(
            "requires Windows SQLCipher, DPAPI and Hello; this is a text lab, not native voice acceptance"
        )
    repo = Path(__file__).resolve().parents[3]
    verify_source(repo, args.source_commit)
    from jarvis.authority.tooling import (
        resolve_opa_binary,
        resolve_windows_hello_helper,
    )
    from jarvis.machine_config import load_machine_settings

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
    with project_lab_environment(profile, repo):
        config = JarvisConfig.from_environment()
        if config.ai_provider != "gemini":
            parser.error("existing Gemini configuration required")
        asyncio.run(run_text_lab(config, profile.parent, model=args.model))


if __name__ == "__main__":
    main()
