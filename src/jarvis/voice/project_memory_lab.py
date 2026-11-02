"""Exact-source, isolated Windows TEXT acceptance for project memory.

No microphone or paid fallback is enabled. Native STT/TTS qualification is a
separate blocked gate. Existing Gemini free credentials, SQLCipher/DPAPI, OPA and
Windows Hello are reused; original machine settings are not edited.
"""

from __future__ import annotations

import inspect
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


def build_project_personal_session(
    conversation, memory, capability, *, read_issuer=None, read_grant=None
):
    """Personal facts for one request.

    With ``read_issuer``/``read_grant`` the read uses the owner's read-only
    session grant (one Hello per session). Without them every read asks for a
    fresh exact-request approval, as before. Writes always ask separately.
    """
    from jarvis.voice.personal_context import PersonalContextSession

    return PersonalContextSession(
        conversation=conversation,
        retrieval=memory.retrieval,
        authority=capability,
        retire=lambda: None,
        learning_authority=read_issuer,
        learning_grant=read_grant,
        explicit_question_queries=True,
    )


def build_session_personal_factory(memory, capability, *, provider="gemini"):
    """Factory for the coordinator plus the session it shares across requests."""
    from jarvis.voice.project_personal_session import (
        LazyPersonalContext,
        PersonalReadSession,
    )

    session = PersonalReadSession(
        lambda: capability.personal_context_session_authority, provider=provider
    )

    def factory(conversation):
        return LazyPersonalContext(
            lambda issuer, grant: build_project_personal_session(
                conversation,
                memory,
                capability,
                read_issuer=issuer,
                read_grant=grant,
            ),
            session,
        )

    return factory, session


async def reauthorize_lab_history(access, coordinator, *, personal_factory=None):
    """Explicit owner command only; denial never restores the old grant."""
    import asyncio
    from uuid import uuid4

    from jarvis.memory.project_access import ProjectArchiveAccess
    from jarvis.voice.project_conversation import ProjectConversationCoordinator

    coordinator.invalidate("owner_reauthorization")
    access.authority.revoke(access.grant, "owner_reauthorization")
    grant = await asyncio.to_thread(access.authority.open, str(uuid4()), "gemini")
    fresh = ProjectArchiveAccess(access.store, authority=access.authority, grant=grant)
    return fresh, ProjectConversationCoordinator(
        fresh,
        source_clearance=standard_history_source,
        personal_factory=personal_factory,
    )


async def _close_lab_resources(
    *,
    coordinator,
    authority,
    capability,
    routing,
    memory,
    lock,
    unlock,
    personal_session=None,
):
    """Try every release; the caller preserves the primary exception afterward."""
    failures = []

    async def attempt(component, close):
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except BaseException as exc:  # noqa: BLE001 - caller propagates primary/first failure after all releases
            # Includes cancellation: release remaining resources before propagating.
            failures.append((component, exc))

    if coordinator is not None:
        await attempt("coordinator", lambda: coordinator.invalidate("shutdown"))
    if personal_session is not None:
        await attempt("personal_session", personal_session.close)
    await attempt("authority", authority.close)
    await attempt("capability", capability.close)
    if routing is not None:
        await attempt("routing", routing.aclose)
    await attempt("memory", memory.close)
    await attempt("lock_unlock", lambda: (lock.seek(0), unlock()))
    await attempt("lock_close", lock.close)
    return failures


async def run_text_lab(
    config,
    root: Path,
    *,
    model: str,
    seed_acceptance=False,
    development_case=None,
    personal_acceptance=False,
    source_commit=None,
):
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
    from jarvis.memory.project_routing import ProjectClarificationRequired
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
    personal_session = None
    contract_observations = []
    terminal_error = None
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

        # One Hello opens a read-only personal-fact session for this lab run
        # (30 min, 10 min idle, ends on Windows lock); writes ask separately.
        personal, personal_session = build_session_personal_factory(memory, capability)

        coordinator = ProjectConversationCoordinator(
            access, source_clearance=standard_history_source, personal_factory=personal
        )
        if personal_acceptance:
            from jarvis.voice.project_contract_diagnostics import (
                observe_contract_failures,
            )
            from jarvis.voice.project_personal_acceptance import run_personal_acceptance

            print(
                "PERSONAL FIXTURE: fictional diet, two projects, correction, three questions. Fresh Hello approvals for mutations; one Hello opens the personal-read session. Free lane only; no setup inference or automatic retry.",
                flush=True,
            )
            with observe_contract_failures() as contract_observations:
                return await run_personal_acceptance(
                    root,
                    memory=memory,
                    capability=capability,
                    coordinator=coordinator,
                    access=access,
                    provider=provider,
                    source_commit=source_commit,
                    model=model,
                )
        if development_case is not None:
            from jarvis.voice.project_contract_diagnostics import (
                observe_contract_failures,
            )
            from jarvis.voice.project_memory_development import (
                run_case_question,
                seed_development_case,
            )

            manifest = await seed_development_case(access, development_case)
            with (root / "development-fixture.json").open(
                "x", encoding="utf-8"
            ) as stream:
                json.dump(manifest, stream)
            print(
                "DEVELOPMENT FIXTURE: 60 fictional events / 3 projects seeded locally; zero setup model calls. One question; no automatic retry.",
                flush=True,
            )
            with observe_contract_failures() as contract_observations:
                return await run_case_question(
                    development_case, manifest, coordinator, access, provider
                )
        controls = ProjectControls(access)
        manifest_path = root / "acceptance-fixture.json"
        if seed_acceptance:
            from jarvis.voice.project_memory_acceptance import seed_acceptance_fixture

            manifest = await seed_acceptance_fixture(access)
            with manifest_path.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream)
            print(
                "SYNTHETIC FIXTURE: 43 local fictional events seeded; zero provider calls. User facts conflict with an assistant reply. Selected Nepal acceptance."
            )
        elif manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = None
        quarantine = await controls.quarantine_report()
        if quarantine.count:
            where = ", ".join(f"{t} ({n})" for t, n in quarantine.projects)
            print(
                f"UPGRADE CHECK: {quarantine.count} older Jarvis replies/tool results may "
                f"repeat a project you forgot: {where}. Nothing was deleted; they are "
                "hidden from Jarvis until you decide. /repair inspect shows them; "
                "/repair delete or /repair restore asks for Windows Hello."
            )
        print(
            "TEXT LAB: original history retained locally when eligible. Configured Free credential lane only; no Paid fallback. Windows Hello grants project retention; one more Hello opens personal reads for 30 min (10 min idle); corrections/deletion keep their own approvals."
        )
        print(
            "Commands: /projects /inspect /pause /resume /forget /sleep /reauthorize /repair /quit. Normal text selects explicit projects and asks questions."
        )
        while True:
            text = await asyncio.to_thread(input, "Jarvis> ")
            if text == "/quit":
                break
            if not text.strip():
                continue
            try:
                if text == "/reauthorize":
                    # Renewal also ends the personal-read session; the next
                    # personal question asks for a fresh owner approval.
                    personal_session.close("owner_reauthorization")
                    try:
                        access, coordinator = await reauthorize_lab_history(
                            access, coordinator, personal_factory=personal
                        )
                        controls = ProjectControls(access)
                        print(
                            "History authorization renewed with fresh owner approval. No question was retried."
                        )
                    except (PermissionError, ValueError, RuntimeError, OSError):
                        print(
                            "History reauthorization failed; prior grant remains revoked. Use /reauthorize to request fresh owner approval, or /quit."
                        )
                    continue
                if text == "/sleep":
                    coordinator.invalidate("sleep")
                    print("Listening segment closed; project selection retained.")
                    continue
                if text.startswith("/repair"):
                    action = text.removeprefix("/repair").strip() or "status"
                    if action == "status":
                        report = await controls.quarantine_report()
                        print(json.dumps(asdict(report), ensure_ascii=False))
                    elif action == "inspect":
                        for (
                            title,
                            at,
                            role,
                            body,
                        ) in await controls.inspect_quarantine():
                            print(
                                json.dumps([title, at, role, body], ensure_ascii=False)
                            )
                    elif action in {"delete", "restore"}:
                        coordinator.invalidate("quarantine_" + action)
                        report = await controls.resolve_quarantine(action)
                        print(
                            f"Upgrade quarantine {action}d: {report.count} messages."
                            if report.count
                            else "Nothing is quarantined."
                        )
                    else:
                        raise ValueError(
                            "use /repair, /repair inspect, delete or restore"
                        )
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
                        preview = await controls.preview_forget(project_id)
                        if preview.derived_sources:
                            print(
                                f"Forgetting also removes {preview.derived_sources} Jarvis "
                                "replies/tool results generated with this project's content in: "
                                + ", ".join(preview.affected_projects)
                                + ". Your own messages there are kept."
                            )
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
                observer = None
                if manifest:
                    from jarvis.voice.project_memory_acceptance import (
                        FixtureEvidenceProvider,
                    )

                    observer = FixtureEvidenceProvider(provider, access, manifest)
                result = await coordinator.respond(
                    conversation,
                    turn,
                    provider=observer or provider,
                    authorize=access.current,
                )
                await coordinator.validate_for_release(result)
                if not coordinator.validate_current(result.packet):
                    raise PermissionError("answer invalidated")
                print(result.announcement)
                print(result.answer)
                receipt = await coordinator.record_assistant(
                    conversation, result, delivered_text=result.answer
                )
                if manifest:
                    from jarvis.voice.project_memory_acceptance import fixture_evidence

                    evidence = fixture_evidence(manifest, result, observer=observer)
                    if evidence is not None:
                        print("FIXTURE_EVIDENCE " + json.dumps(evidence))
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
            except ProjectClarificationRequired as exc:
                print(exc.question)
            except (PermissionError, ValueError, RuntimeError, OSError) as exc:
                print(
                    f"NOT COMPLETED: {json.dumps(coordinator.diagnostics())}; error={type(exc).__name__}. Inspect saved sources before retrying; no successful-save claim for failed stage."
                )
    except BaseException as exc:
        terminal_error = exc
        if (development_case is not None or personal_acceptance) and isinstance(
            exc, Exception
        ):
            from jarvis.voice.project_contract_diagnostics import DevelopmentCaseFailure

            terminal_error = DevelopmentCaseFailure(
                exc, coordinator, contract_observations
            )
            raise terminal_error from None
        raise
    finally:
        cleanup = await _close_lab_resources(
            coordinator=coordinator,
            authority=authority,
            capability=capability,
            routing=routing,
            memory=memory,
            lock=lock,
            unlock=lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1),
            personal_session=personal_session,
        )
        if cleanup:
            from jarvis.voice.project_contract_diagnostics import DevelopmentCaseFailure

            metadata = [
                {"component": component, "error": type(error).__name__}
                for component, error in cleanup
            ]
            if isinstance(terminal_error, DevelopmentCaseFailure):
                terminal_error.report["cleanup_errors"] = metadata
            elif terminal_error is None:
                first_error = cleanup[0][1]
                if (development_case is not None or personal_acceptance) and isinstance(
                    first_error, Exception
                ):
                    failure = DevelopmentCaseFailure(
                        first_error, coordinator, contract_observations
                    )
                    failure.report.update(stage="cleanup", cleanup_errors=metadata)
                    raise failure from None
                raise first_error


def run_development_mode(args, repo, tool_paths):
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.voice.project_memory_development import (
        load_cases,
        run_development_batch,
    )

    # Validate frozen data before creating profiles or requesting owner approvals.
    cases = load_cases(repo)
    selected = getattr(args, "development_case", None)
    if selected is not None:
        cases = tuple(c for c in cases if c.question["id"] == selected)
        if not cases:
            raise ValueError("unknown frozen development case")

    def run_case(case, root):
        profile = prepare_project_profile(
            args.profile,
            root,
            resume=False,
            commit=args.source_commit,
            tool_paths=tool_paths,
        )
        with project_lab_environment(profile, repo):
            config = JarvisConfig.from_environment()
            if config.ai_provider != "gemini":
                raise ValueError("existing Gemini configuration required")
            return asyncio.run(
                run_text_lab(config, root, model=args.model, development_case=case)
            )

    print(
        f"DEVELOPMENT BATCH: {len(cases)} question(s), each with a fresh isolated profile and Windows Hello history approval. Free credential lane only; no Paid fallback. Stops on first failure. Answers require manual review.",
        flush=True,
    )
    return run_development_batch(
        args.lab_root,
        cases,
        run_case,
        source_commit=args.source_commit,
        model=args.model,
    )


def main():
    import argparse
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.machine_config import default_machine_config_path
    from jarvis.voice.project_memory_development import CASE_IDS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=default_machine_config_path())
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--resume-lab", action="store_true")
    parser.add_argument("--seed-acceptance", action="store_true")
    parser.add_argument("--development-batch", action="store_true")
    parser.add_argument("--development-case", choices=CASE_IDS)
    parser.add_argument("--personal-acceptance", action="store_true")
    args = parser.parse_args()
    if args.personal_acceptance and (
        args.resume_lab
        or args.seed_acceptance
        or args.development_batch
        or args.development_case
    ):
        parser.error("personal acceptance requires a fresh standalone lab")
    if args.development_case and not args.development_batch:
        parser.error("--development-case requires --development-batch")
    if args.development_batch and (args.seed_acceptance or args.resume_lab):
        parser.error(
            "development batch requires a new isolated lab, without acceptance seeding or resume"
        )
    if args.seed_acceptance and args.resume_lab:
        parser.error(
            "acceptance seeding requires a new isolated lab, never --resume-lab"
        )
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
    if args.development_batch:
        summary = run_development_mode(args, repo, tool_paths)
        if summary["failed"] or summary["reporting_errors"]:
            raise SystemExit(1)
        return
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
        try:
            asyncio.run(
                run_text_lab(
                    config,
                    profile.parent,
                    model=args.model,
                    seed_acceptance=args.seed_acceptance,
                    personal_acceptance=args.personal_acceptance,
                    source_commit=args.source_commit,
                )
            )
        except Exception as exc:
            from jarvis.voice.project_contract_diagnostics import DevelopmentCaseFailure

            if not args.personal_acceptance or not isinstance(
                exc, DevelopmentCaseFailure
            ):
                raise
            from jarvis.voice.project_personal_acceptance import record_runtime_failure

            record_runtime_failure(profile.parent, exc.report)
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
