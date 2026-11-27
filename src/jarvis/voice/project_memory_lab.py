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

from jarvis.memory.project_history_source import (
    standard_history_source,
)
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


RECOVERY_SOURCE = "recovery-source.json"
LAB_ONLY_SOURCE_PATHS = frozenset(
    "src/jarvis/voice/" + name + ".py"
    for name in (
        "heldout_player",
        "paid_acceptance_budget",
        "personal_memory_acceptance",
        "project_memory_lab",
    )
)


def _same_product_source(source: Path, original: str, recovery: str) -> bool:
    """Consent recovery may change lab tooling, never the product it tested."""
    if any(
        not isinstance(sha, str)
        or len(sha) != 40
        or any(c not in "0123456789abcdef" for c in sha)
        for sha in (original, recovery)
    ):
        return False
    try:
        changed = subprocess.check_output(
            [
                "git",
                "-C",
                str(source),
                "diff",
                "--name-only",
                "--no-renames",
                original,
                recovery,
                "--",
                "src",
                "policies",
                "pyproject.toml",
                "uv.lock",
                "requirements*.txt",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return False
    return not (set(changed) - LAB_ONLY_SOURCE_PATHS)


def _resume_allowed(
    lab: Path,
    marker: Path,
    commit,
    recovery_resume: bool,
    *,
    source: Path | None = None,
) -> bool:
    """A lab resumes on the commit its marker records. The only exception is
    the slice-1 D17 consent recovery: its first entry may run a later commit
    (the runner then validates the recovery before anything is sent and
    records recovery-source.json), and only that recorded recovery commit may
    continue afterwards. The marker itself is never rewritten."""
    if not marker.is_file():
        return False
    text = marker.read_text()
    if text == json.dumps({"kind": MARKER, "commit": commit}, sort_keys=True):
        return True
    try:
        recorded = json.loads(text)
    except ValueError:
        return False
    if recorded.get("kind") != MARKER or recorded.get("commit") == commit:
        return False
    if source is None or not _same_product_source(
        source, recorded.get("commit"), commit
    ):
        return False
    path = lab / RECOVERY_SOURCE
    if path.is_file():
        try:
            recovery = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return False
        return (
            recovery.get("original_commit") == recorded.get("commit")
            and recovery.get("recovery_commit") == commit
        )
    return recovery_resume


def prepare_project_profile(
    source: Path,
    lab: Path,
    *,
    resume: bool,
    commit=None,
    tool_paths=None,
    recovery_resume=False,
):
    source = source.resolve(strict=True)
    lab = lab.resolve()
    if lab == source.parent or source.parent.is_relative_to(lab):
        raise ValueError("profile must be isolated")
    marker = lab / "project-memory.marker"
    if resume:
        if not _resume_allowed(lab, marker, commit, recovery_resume, source=source):
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
    context_eval_arm=None,
    context_eval_case=None,
    seed_voice_eval=False,
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
        if seed_voice_eval:
            from jarvis.voice.project_personal_context_eval import (
                seed_voice_eval as seed,
            )

            print(
                "VOICE EVAL SEED: fictional Spiti Valley trip (selected) and Home "
                "errands projects; one fresh Hello saves the fictional vehicles. "
                "No model call.",
                flush=True,
            )
            return await seed(
                root,
                memory=memory,
                capability=capability,
                access=access,
                source_commit=source_commit,
            )
        if context_eval_arm is not None:
            from jarvis.voice.project_personal_context_eval import run_context_eval

            print(
                f"CONTEXT EVALUATION ({context_eval_arm} saved facts): fictional "
                "projects and facts, three questions in fresh sessions. "
                + (
                    "Fresh Hello approvals for each fictional memory command; "
                    if context_eval_arm == "with"
                    else "No memory commands; "
                )
                + "one Hello opens personal reads FIRST, before any question, as "
                "live Jarvis does. Free lane only; no automatic retry.",
                flush=True,
            )
            return await run_context_eval(
                root,
                arm=context_eval_arm,
                memory=memory,
                capability=capability,
                coordinator=coordinator,
                access=access,
                provider=provider,
                source_commit=source_commit,
                model=model,
                personal_session=personal_session,
                case=context_eval_case,
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
                if result.announcement:
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


def run_context_eval_mode(args, repo, tool_paths):
    """Both arms (or the one named by --context-eval-arm), each in its own
    fresh isolated profile: without saved facts first (no memory commands),
    then with them. Stops on the first failure."""
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.voice.project_personal_context_eval import ARMS

    args.lab_root.mkdir(parents=True, exist_ok=False)
    # One arm alone (--context-eval-arm) reruns an unfinished half in its own
    # new lab root; the completed half and its model calls are never repeated.
    for arm in (args.context_eval_arm,) if args.context_eval_arm else ARMS:
        root = args.lab_root / arm
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
            asyncio.run(
                run_text_lab(
                    config,
                    profile.parent,
                    model=args.model,
                    context_eval_arm=arm,
                    context_eval_case=args.context_eval_case,
                    source_commit=args.source_commit,
                )
            )


# Owner instruction 2026-11-24: the checkpoint may use at most USD 0.10 of the
# shared USD 1 budget.
CHECKPOINT_ALLOWANCE = ("slice1-paid-checkpoint-1", 100_000)
# Owner instruction 2026-11-24 14:48: the D17 consent recovery reruns one
# turn; it may use at most USD 0.05 of the same shared budget.
D17_RECOVERY_ALLOWANCE = ("slice1-paid-d17-recovery-1", 50_000)
# This approval is one lifetime budget, not a new budget per lab or filename.
APPROVED_PAID_LEDGER = Path(r"E:\Jarvis\Temp\slice1-paid-budget\ledger.sqlite3")
LANE_MARKER = "acceptance-lane.json"


def check_lane(root: Path, lane: str, paid_ledger) -> None:
    """Pin lane and the designated shared ledger before clients are created."""
    if lane not in {"free", "paid"}:
        raise ValueError("lane must be free or paid")
    if (lane == "paid") != (paid_ledger is not None):
        raise ValueError("the paid lane requires its ledger, and only it")
    ledger = Path(paid_ledger).resolve() if paid_ledger is not None else None
    if ledger is not None:
        if ledger != APPROVED_PAID_LEDGER.resolve():
            raise ValueError("Paid ledger differs from the approved shared ledger")
        if not ledger.is_file():
            raise ValueError(
                "Shared Paid ledger is missing; explicit budget recovery required"
            )
    expected = {"lane": lane, "ledger": str(ledger) if ledger is not None else None}
    marker = root / LANE_MARKER
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != expected:
        raise ValueError("This lab cannot change its lane or shared Paid ledger")
    steps_file = root / "acceptance-steps.jsonl"
    if steps_file.exists():
        first = steps_file.read_text(encoding="utf-8").splitlines()[:1]
        row = json.loads(first[0]) if first else {}
        recorded = row.get("lane")
        if recorded is not None and recorded != lane:
            raise ValueError(
                f"this lab ran on the {recorded} lane; it cannot continue on {lane}"
            )
        if recorded == "paid":
            previous = (row.get("paid_budget") or {}).get("ledger")
            if not previous or Path(previous).resolve() != ledger:
                raise ValueError("This lab's recorded Paid ledger cannot be replaced")
    if not marker.exists():
        try:
            with marker.open("x", encoding="utf-8") as stream:
                json.dump(expected, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if json.loads(marker.read_text(encoding="utf-8")) != expected:
                raise ValueError(
                    "This lab cannot change its lane or shared Paid ledger"
                ) from None


async def run_slice1_acceptance(
    config,
    root: Path,
    *,
    model,
    source_commit,
    hashes,
    groups,
    retry_interrupted,
    call_spacing_seconds,
    lane="free",
    paid_ledger=None,
    checkpoint=False,
    recover_d17_consent=False,
    heldout=None,
    stop_on="any",
):
    """Frozen D1-D27 development acceptance in this isolated lab profile.

    ``heldout`` (heldout_player.load_script result plus its path) runs a
    transcribed held-out script instead, Free lane only: the approved Paid
    budget is for development acceptance only.

    lane "free" (default) uses the Free credential only. lane "paid" (owner
    approval 2026-11-23, USD 1, development acceptance only) uses
    JARVIS_GEMINI_PAID_API_KEY only, for extraction, resolution and answers,
    with every request reserved in the shared durable ledger ``paid_ledger``.
    A lab never changes lane and never falls back between lanes."""
    import asyncio
    import msvcrt
    from uuid import uuid4

    from jarvis.ai_provider import gemini_credential_ref
    from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.hands.provider_adapters import build_structured_output_client
    from jarvis.memory.learning_extractors import build_learning_adapters
    from jarvis.memory.runtime import build_default_memory_runtime
    from jarvis.model_routing.runtime import build_routing_runtime
    from jarvis.provider_retry import policy_summary
    from jarvis.voice.personal_memory_acceptance import (
        CHECKPOINT_STOP_AFTER,
        AcceptanceRunner,
        FreeLaneDriverClient,
        FreeLanePacer,
        LabDeps,
        ResultLog,
    )
    from jarvis.work.privacy import build_default_work_payload_codec
    from jarvis.work.store import SQLiteWorkStore

    check_lane(root, lane, paid_ledger)
    if checkpoint and lane != "paid":
        raise ValueError("the checkpoint is a Paid-lane control")
    if recover_d17_consent and (checkpoint or tuple(groups or ()) != ("story",)):
        raise ValueError("the D17 recovery runs alone, on the story group")
    lock = (root / "project-memory.lock").open("a+b")
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError("another process owns this lab") from None
    broker = CapabilityAuthorityBroker()
    capability = CapabilityRuntime(
        executors=(), resolver=CapabilityResolver((), builtins=()), authority=broker
    )
    routing = None
    grant = None
    driver = None
    ledger = None
    withheld_free_key = None
    try:
        if lane == "paid":
            from jarvis.voice.paid_acceptance_budget import (
                BUDGET_ID,
                CEILING_MICRO_USD,
                PAID_CREDENTIAL_REF,
                PaidBudgetLedger,
                PaidLaneDriverClient,
                build_paid_clients,
            )

            # Paid lane only: no router, no Free credential. Learning uses the
            # Paid key directly with SDK retries off (Jarvis's learning runtime
            # stays the single, bounded retry owner); answers likewise, with
            # the text driver as retry owner. Every request is reserved in the
            # shared ledger before it is sent.
            ledger = PaidBudgetLedger(paid_ledger)
            allowance = (
                CHECKPOINT_ALLOWANCE
                if checkpoint
                else D17_RECOVERY_ALLOWANCE
                if recover_d17_consent
                else None
            )
            adapter, answer = build_paid_clients(
                model, ledger, lab=str(root), allowance=allowance
            )
            # The Free credential is withheld from this process for the whole
            # run, so no code path can reach the Free lane by accident.
            withheld_free_key = os.environ.pop(gemini_credential_ref("free"), None)
            extractor = resolver = adapter
            driver = PaidLaneDriverClient(answer)
            lane_fields = {
                "lane": "paid",
                "credential_ref": PAID_CREDENTIAL_REF,
                "paid_budget": {
                    "budget_id": BUDGET_ID,
                    "ceiling_usd": CEILING_MICRO_USD / 1e6,
                    "ledger": str(paid_ledger),
                    "allowance": (
                        {
                            "allowance_id": allowance[0],
                            "cap_usd": allowance[1] / 1e6,
                        }
                        if allowance
                        else None
                    ),
                },
            }
        else:
            path = root / "routing.sqlite3"
            work_store = SQLiteWorkStore(
                path, payload_codec=build_default_work_payload_codec(path)
            )
            # Free credential lane only: paid targets are disabled for this lab.
            routing = build_routing_runtime(
                work_store=work_store,
                provider="gemini",
                model=model,
                config=replace(config.gemini_fallback, enabled=False),
            )
            # Answer calls: the Free credential only, SDK retries off, no router
            # and no Paid credential (a Paid request is impossible). The text
            # driver is the single retry owner for these calls.
            driver = FreeLaneDriverClient(
                build_structured_output_client(
                    provider="gemini",
                    model=model,
                    provider_retries=False,
                    credential_ref=gemini_credential_ref("free"),
                    max_output_tokens=2048,
                )
            )
            # With paid routing disabled the learning adapters use the Free key
            # directly, with the SDK's own retries off; Jarvis's learning runtime
            # is their single retry owner (bounded, temporary failures only).
            extractor, resolver = build_learning_adapters(
                "gemini", routing_runtime=routing
            )
            lane_fields = {
                "lane": "free",
                "credential_ref": gemini_credential_ref("free"),
            }
        models = {
            "answer_model": model,
            "learning_model": getattr(extractor, "model_name", None),
            **lane_fields,
            "call_spacing_seconds": float(call_spacing_seconds),
            "retry_policy": policy_summary(),
        }
        # One limiter shared by learning and answer calls (same key).
        pacer = FreeLanePacer(call_spacing_seconds)
        lane_text = (
            "PAID lane only (JARVIS_GEMINI_PAID_API_KEY for extraction, resolution "
            f"and answers; shared budget USD {CEILING_MICRO_USD / 1e6:.2f}, ledger "
            f"{paid_ledger}; no Free fallback)"
            if lane == "paid"
            else f"Free lane only ({gemini_credential_ref('free')}; no Paid fallback)"
        )
        if ledger is not None:
            print(
                "PAID BUDGET BEFORE RUN: " + json.dumps(ledger.snapshot()), flush=True
            )
        print(
            f"SLICE-1 DEVELOPMENT ACCEPTANCE [{lane.upper()} LANE] (D1-D27, "
            "fictional data, isolated lab). "
            f"Answer model {model}; learning model {models['learning_model']}. "
            f"{lane_text}; a temporary provider error (503/500) is retried at most "
            "twice inside its deadline, never a 429, stall or wrong answer; model "
            f"calls start at least "
            f"{float(call_spacing_seconds):g} s apart. Windows Hello: (1) now, to open the "
            "owner learning session used for learning and reads; (2) at D3, to save "
            "'Dell XPS; iPad Air'; (3) at D17, to forget the Classic 350. Progress: "
            "one line per step below and in acceptance-steps.jsonl.",
            flush=True,
        )
        learning_authority = capability.personal_learning_authority
        try:
            grant = await asyncio.to_thread(
                capability.open_personal_learning, str(uuid4()), "gemini"
            )
        except PermissionError:
            print(
                "NOT STARTED: the learning session was not approved. Nothing was "
                "run; rerun the same command to try again.",
                flush=True,
            )
            raise SystemExit(1) from None

        async def open_memory(db_path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            memory = build_default_memory_runtime(db_path)
            await memory.start()
            return memory

        deps = LabDeps(
            open_memory=open_memory,
            capability=capability,
            learning_authority=learning_authority,
            learning_grant=grant,
            extractor=extractor,
            resolver=resolver,
            driver_client=driver,
            models=models,
            pacer=pacer,
        )
        log = ResultLog(
            root, commit=source_commit, hashes=hashes, models=models, echo=True
        )
        # The Paid lane always stops on a definite failure (FAIL, or UNTESTED
        # from a broken prerequisite); the checkpoint pauses after story-05c.
        held = {}
        if heldout is not None:
            groups_map, checks_map, planned, script_sha, script_path = heldout
            groups = planned
            held = {
                "groups_map": groups_map,
                "checks_map": checks_map,
                "planned_cases": planned,
                "not_run_here": {},
            }
            log.event(
                {
                    "kind": "heldout_script",
                    "path": str(script_path),
                    "sha256": script_sha,
                    "cases": list(planned),
                }
            )
            print(
                f"HELD-OUT EXECUTION (once, frozen code): {len(planned)} cases from"
                f" {script_path} (sha256 {script_sha}); every case is recorded for"
                " manual grading against the sealed expectations. Windows Hello:"
                " now (owner learning session) and at any turn marked"
                " explicit_tools; the development-case prompts above do not apply.",
                flush=True,
            )
        runner = AcceptanceRunner(
            root,
            deps,
            log,
            retry_interrupted=retry_interrupted,
            stop_after=CHECKPOINT_STOP_AFTER if checkpoint else None,
            stop_on_failure=lane == "paid",
            stop_on=stop_on,
            recover_d17_consent=recover_d17_consent,
            **held,
        )
        summary = await runner.run(groups)
        if summary.get("run_state") == "checkpoint_paused_for_review":
            print(
                f"{'D17 RECOVERY' if recover_d17_consent else 'CHECKPOINT'} "
                f"PAUSED FOR REVIEW [{lane.upper()} LANE] after "
                f"{runner.stop_after}: "
                + json.dumps({c: r["status"] for c, r in summary["cases"].items()})
                + f" | results in {root}. Completed steps are kept; continuing "
                "with -ResumeLab does not repeat them.",
                flush=True,
            )
            return summary
        print(
            f"DEVELOPMENT ACCEPTANCE COMPLETE [{lane.upper()} LANE]: "
            + json.dumps({c: r["status"] for c, r in summary["cases"].items()})
            + f" | untested={summary['untested']} | results in {root}",
            flush=True,
        )
        return summary
    finally:
        if withheld_free_key is not None:
            os.environ[gemini_credential_ref("free")] = withheld_free_key
        if ledger is not None:
            snapshot = ledger.snapshot()
            (root / "paid-budget-snapshot.json").write_text(
                json.dumps({**snapshot, "lab": str(root)}, indent=2), encoding="utf-8"
            )
            print("PAID BUDGET AFTER RUN: " + json.dumps(snapshot), flush=True)
            ledger.close()
        if grant is not None:
            capability.close_personal_learning(grant)
        capability.close()
        if driver is not None:
            await driver.aclose()
        if routing is not None:
            await routing.aclose()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def run_slice1_acceptance_mode(args, repo, tool_paths):
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.voice.personal_memory_acceptance import (
        GROUP_ORDER,
        AcceptanceInterrupted,
        AcceptanceRecoveryRefused,
        AcceptanceStoppedOnFailure,
        active_amendments,
        frozen_hashes,
    )

    # Verify the frozen case files and the approved amendments before any
    # profile, approval or model call.
    hashes = frozen_hashes(repo)
    for amendment in active_amendments(repo):
        print(
            f"Acceptance {amendment['id']}: ACTIVE ({amendment['file']},"
            f" sha256 {amendment['sha256']})",
            flush=True,
        )
    groups = tuple(args.slice1_group) if args.slice1_group else GROUP_ORDER
    heldout = None
    if args.slice1_heldout_script is not None:
        from jarvis.voice.heldout_player import load_script

        heldout = (*load_script(args.slice1_heldout_script), args.slice1_heldout_script)
    profile = prepare_project_profile(
        args.profile,
        args.lab_root,
        resume=args.resume_lab,
        commit=args.source_commit,
        tool_paths=tool_paths,
        recovery_resume=args.recover_d17_consent,
    )
    with project_lab_environment(profile, repo):
        config = JarvisConfig.from_environment()
        if config.ai_provider != "gemini":
            raise ValueError("existing Gemini configuration required")
        try:
            return asyncio.run(
                run_slice1_acceptance(
                    config,
                    profile.parent,
                    model=args.model,
                    source_commit=args.source_commit,
                    hashes=hashes,
                    groups=groups,
                    retry_interrupted=args.retry_interrupted,
                    call_spacing_seconds=args.call_spacing_seconds,
                    lane="paid" if args.paid_lane else "free",
                    paid_ledger=args.paid_budget_ledger,
                    checkpoint=args.paid_checkpoint,
                    stop_on=args.slice1_stop_on,
                    recover_d17_consent=args.recover_d17_consent,
                    heldout=heldout,
                )
            )
        except AcceptanceRecoveryRefused as exc:
            print(f"RECOVERY REFUSED (nothing was run): {exc}", flush=True)
            raise SystemExit(4) from None
        except AcceptanceStoppedOnFailure as exc:
            print(
                f"[{'PAID' if args.paid_lane else 'FREE'} LANE] STOPPED ON A DEFINITE "
                f"ACCEPTANCE FAILURE: {exc}. No dependent case was run; review "
                "before any further spending.",
                flush=True,
            )
            raise SystemExit(3) from None
        except AcceptanceInterrupted as exc:
            print(
                f"[{'PAID' if args.paid_lane else 'FREE'} LANE] INTERRUPTED (any bounded retries are recorded; none remain): {exc}. "
                "Completed steps are kept. Continue later with the same command plus "
                "-ResumeLab; an interrupted step reruns only with -RetryInterrupted.",
                flush=True,
            )
            raise SystemExit(2) from None


def _require_windows(parser):
    if os.name != "nt":
        parser.error(
            "requires Windows SQLCipher, DPAPI and Hello; this is a text lab, not native voice acceptance"
        )


def main(argv=None):
    import argparse
    import asyncio

    from jarvis.config import JarvisConfig
    from jarvis.machine_config import default_machine_config_path
    from jarvis.voice.personal_memory_acceptance import GROUP_ORDER as SLICE1_GROUPS
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
    parser.add_argument("--context-eval", action="store_true")
    parser.add_argument("--context-eval-arm", choices=("without", "with"))
    parser.add_argument("--context-eval-case", choices=("travel", "diet", "device"))
    parser.add_argument("--seed-voice-eval", action="store_true")
    parser.add_argument("--slice1-acceptance", action="store_true")
    parser.add_argument(
        "--slice1-group",
        action="append",
        choices=SLICE1_GROUPS,
    )
    parser.add_argument("--retry-interrupted", action="store_true")
    parser.add_argument("--call-spacing-seconds", type=float, default=None)
    parser.add_argument("--paid-lane", action="store_true")
    parser.add_argument("--paid-budget-ledger", type=Path, default=None)
    parser.add_argument("--paid-checkpoint", action="store_true")
    parser.add_argument("--recover-d17-consent", action="store_true")
    parser.add_argument("--slice1-heldout-script", type=Path, default=None)
    # "invariant": the Paid lane stops only on a failed safety invariant;
    # model-quality failures are measured (bounded final evaluation).
    parser.add_argument("--slice1-stop-on", choices=("any", "invariant"), default="any")
    args = parser.parse_args(argv)
    if args.slice1_stop_on != "any" and not args.paid_lane:
        parser.error("--slice1-stop-on applies to the Paid lane")
    if args.slice1_heldout_script is not None and (
        not args.slice1_acceptance
        or args.slice1_group
        or args.paid_lane
        or args.paid_checkpoint
        or args.recover_d17_consent
        or args.resume_lab
    ):
        parser.error(
            "--slice1-heldout-script runs once in a fresh lab with --slice1-acceptance,"
            " Free lane only (the approved Paid budget excludes held-out)"
        )
    if (args.paid_lane or args.paid_budget_ledger) and not args.slice1_acceptance:
        parser.error("--paid-lane is only for --slice1-acceptance")
    if args.recover_d17_consent and not (args.resume_lab and args.slice1_acceptance):
        parser.error("--recover-d17-consent continues an existing acceptance lab")
    if args.paid_checkpoint and not args.paid_lane:
        parser.error("--paid-checkpoint requires --paid-lane")
    if args.paid_lane != (args.paid_budget_ledger is not None):
        parser.error("--paid-lane and --paid-budget-ledger go together")
    if args.slice1_acceptance and (
        args.seed_acceptance
        or args.development_batch
        or args.development_case
        or args.personal_acceptance
        or args.context_eval
        or args.seed_voice_eval
    ):
        parser.error("slice-1 acceptance runs alone in its own lab")
    if (args.slice1_group or args.retry_interrupted) and not args.slice1_acceptance:
        parser.error("--slice1-group/--retry-interrupted require --slice1-acceptance")
    if args.call_spacing_seconds is not None and not args.slice1_acceptance:
        parser.error("--call-spacing-seconds requires --slice1-acceptance")
    if args.slice1_acceptance:
        from jarvis.voice.personal_memory_acceptance import (
            DEFAULT_CALL_SPACING_SECONDS,
        )

        if args.call_spacing_seconds is None:
            args.call_spacing_seconds = DEFAULT_CALL_SPACING_SECONDS
        if not 0 < args.call_spacing_seconds <= 120:
            parser.error("--call-spacing-seconds must be in (0, 120]")
    if args.retry_interrupted and not args.resume_lab:
        parser.error(
            "--retry-interrupted only continues an existing lab (--resume-lab)"
        )
    if args.seed_voice_eval and (
        args.resume_lab
        or args.seed_acceptance
        or args.development_batch
        or args.development_case
        or args.personal_acceptance
        or args.context_eval
    ):
        parser.error("voice evaluation seeding requires a fresh standalone lab")
    if (args.context_eval_arm or args.context_eval_case) and not args.context_eval:
        parser.error("--context-eval-arm/--context-eval-case require --context-eval")
    if args.context_eval and (
        args.resume_lab
        or args.seed_acceptance
        or args.development_batch
        or args.development_case
        or args.personal_acceptance
    ):
        parser.error("context evaluation requires a fresh standalone lab")
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
    _require_windows(parser)
    repo = Path(__file__).resolve().parents[3]
    verify_source(repo, args.source_commit)
    from jarvis.authority.tooling import (
        resolve_opa_binary,
    )
    from jarvis.machine_config import load_machine_settings

    settings = load_machine_settings(args.profile)
    tool_paths = (
        {}
        if args.resume_lab
        else {
            "JARVIS_OPA_PATH": resolve_opa_binary(machine_settings=settings).resolve(),
        }
    )
    if args.slice1_acceptance:
        run_slice1_acceptance_mode(args, repo, tool_paths)
        return
    if args.context_eval:
        run_context_eval_mode(args, repo, tool_paths)
        return
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
                    seed_voice_eval=args.seed_voice_eval,
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
