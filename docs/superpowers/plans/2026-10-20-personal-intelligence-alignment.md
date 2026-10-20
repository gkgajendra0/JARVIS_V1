# Personal Intelligence Audit Reconciliation Plan

> **For agentic workers:** Use the debugging, test-driven-development and verification skills for each fix; independent code review is required before promotion. Track progress in the plan-specific ignored ledger.

**Goal:** Reconcile both chats with the approved personal-assistant goal, repair reproduced contract violations, and identify the remaining gates to active personalized conversation.

**Architecture:** Preserve canonical SQLCipher memory, Conversation/LiveContext, WorkStore/DBOS and Authority. Repair existing boundaries without introducing a competing memory store, changing models/dependencies, activating capture or enabling production context injection.

**Tech Stack:** Existing Python 3.11, SQLite/SQLCipher, LiveKit 1.8.3, DBOS, pytest and Ruff.

**Spec:** [Quality gates](../../QUALITY_GATES.md), [current owner direction](../../CURRENT_PLAN.md), [approved PI architecture](../../research/PERSONAL_INTELLIGENCE_ARCHITECTURE_CANDIDATE_2026-10-19.md).

## Global constraints

- Work from audited main `806fd75def350d2b241cefffdf804bf2c5b3fc6e` on a separate branch in the owner's Desktop checkout.
- Owner-approved native extension remains selected; do not ask for that architecture decision again.
- Use fictional temporary data; do not inspect production memories, logs or credentials.
- No real provider calls, purchases, runtime activation or protected-main merge in this repair slice.
- Raw conversation retention is off by default; session validity and protected payloads remain enforced at consumption boundaries.
- Preserve historical acceptance records and distinguish foundations from active product acceptance.

## Review focus

- A lock/user switch/provider failure between approval and execution must invalidate authority.
- A new utterance with identical text must survive transcript/committed-event deduplication.
- A sensitive owner response must not enter DBOS messages or history as plaintext.
- Concurrent remembers through separate service instances must not create two current values for an explicit key.
- Repeated bounded learning scans must eventually reach later outcomes and retain retryable failures.

## Task 1: Restore runtime security and canonical-turn contracts

**Files:** `src/jarvis/capabilities/authority_bridge.py`, existing authority session primitives, `src/jarvis/voice/livekit_session.py`, `src/jarvis/config.py`; relevant tests.

**Interfaces:** Keep capability authorization/consumption and accepted-turn observers compatible. Bind current Windows-session evidence at authorization and consumption; keep injectable providers for offline tests.

- [x] Add and observe failing tests for lock/unavailable/user-switch invalidation, trust reuse and approval-to-consume transitions.
- [x] Wire existing Windows session evidence into the broker and clear stale trust/deny execution on invalid transitions.
- [x] Add a failing two-utterance transcript-first test using distinct item IDs/activity epochs; preserve one turn per actual utterance and deduplicate duplicate events.
- [x] Add a failing default temporary-log test; disable transcript retention by default without disabling operational evidence.
- [x] Run focused authority, voice, configuration and logging regressions; record RED/GREEN evidence.

## Task 2: Protect durable owner input and advance bounded learning scans

**Files:** `src/jarvis/work/runtime.py`, `dbos_backend.py`, `engine.py`/`store.py` as needed; `engineering_learning/sources.py`, reconciliation and canonical outcome store list methods; corresponding tests.

**Interfaces:** Preserve public owner-input behavior, canonical Work ownership, restart/idempotency and protected storage. DBOS receives only protected data or an opaque, version-bound reference for sensitive input. Preserve existing outcome IDs and reconciliation semantics.

- [x] Add and observe a failing sensitive PIN transport test spanning runtime/backend/engine, including replay/wrong-work/stale waiting state.
- [x] Protect before the DBOS persistence boundary using existing canonical protected storage; keep ordinary responses compatible and fail closed on unavailable protection.
- [x] Add and observe a failing more-than-limit repeated-scan test; implement bounded continuation that reaches later outcomes without dropping retries.
- [x] Run Work, Phase9 input, restart/idempotency and Phase10 regression tests; record evidence.

## Task 3: Make the pinned-SDK context delivery probe executable

**Files:** `src/jarvis/voice/personal_context_live_probe.py`, `tests/test_personal_context_live_probe.py`.

**Interfaces:** Preserve explicit real-provider opt-in and fictional-only inputs. Use the context-update receiver exposed by the pinned LiveKit SDK; retain cleanup, deadlines and sanitized outcomes.

- [x] Write a failing offline execution test with a session-shaped fake lacking `AgentSession.update_chat_ctx`, exercising startup, agent update, reply capture and cleanup.
- [x] Update through the supported agent API; no dependency upgrade or real cloud invocation.
- [x] Check failure/timeout cleanup, default no-network behavior and installed SDK interface compatibility.

## Task 4: Make explicit remember's uniqueness check atomic

**Files:** `src/jarvis/memory/lifecycle.py`, `service.py`, `tests/test_memory_service.py` and lifecycle tests.

**Interfaces:** Preserve `MemoryAlreadyExistsError` for an existing explicit key. Enforce uniqueness inside the canonical serialized writer transaction, including separate facade instances. Do not globally forbid valid multi-assertion semantic memory.

- [x] Add a failing concurrent same-key remember test using actual temporary schema/workers and two service instances.
- [x] Add an explicit-create precondition to the canonical write transaction; translate its collision to the existing facade error.
- [x] Verify exactly one success, one collision, and a usable inspect/correct/forget lifecycle; preserve general lifecycle creation and historical assertions.

## Task 5: Reconcile documentation and evidence

**Files:** `docs/CURRENT_PLAN.md`, `CURRENT_ARCHITECTURE.md`, `PROJECT_STATE.md`, `README.md`, architecture research status and one dated audit report under `docs/research/` as needed.

- [x] Map handover claims, this chat's draft PR287 evidence, merged PRs288–291 and source wiring to verified/partial/unverified states.
- [x] Remove current instructions to repeat approved architecture work or restart accepted engineering phases; preserve dated history.
- [x] Record seven reproduced defects, repairs, limits and the remaining actual selector, identity, delivery, paired-answer and owner-machine gates.
- [x] Keep multilingual requirements and eventual APPLY explicit; do not turn synthetic retrieval or static fixtures into production acceptance.

## Task 6: Verify and prepare review

- [x] Run the full isolated local suite, Ruff lint/format, dependency consistency, documentation links and archived Git-blob integrity.
- [x] Obtain independent whole-branch review; resolve material findings with failing regressions before fixes.
- [ ] Commit/push to a dedicated PR, verify exact-head CI and attach it to this chat. No merge or deployment.
- [ ] Report audit outcome, precise remaining work and any genuinely necessary owner-machine action.
