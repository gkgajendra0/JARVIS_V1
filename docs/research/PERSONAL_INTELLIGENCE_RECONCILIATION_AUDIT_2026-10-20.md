# Personal Intelligence: Cross-Chat Reconciliation Audit

**Date:** 20 October 2026. **Audited baseline:** protected `main`
`806fd75def350d2b241cefffdf804bf2c5b3fc6e` (PR #291).
**Scope:** supplied handover, this chat's decisions/evidence, current plans,
major implementation boundaries and repository-wide automated checks.
This is an audit/repair record under the existing product hierarchy, not a
new North Star or production-personalization acceptance.

**Repair-candidate outcome:** seven audited code areas repaired, documentation
drift reconciled, and two additional input-boundary findings closed after
independent review. Final local verification: **2,548 passed / 8 skipped**;
Ruff lint/format and dependency consistency pass. Actual owner-machine
transition/voice qualification and protected promotion remain separate gates.

## Outcome and direction

The other chat followed the same product direction: extend native JARVIS into
an owner-centered personal assistant which uses authorized context in ordinary
advice. SQLCipher, Conversation/LiveContext, WorkStore/DBOS and Authority remain
canonical. No accepted decision calls for a Letta takeover, primary external
memory service, transcript dumping or local fine-tuning as the next step.

The main problem was incomplete integration and overstated next-action
documents, rather than a wholesale architecture diversion. The merged work
provides useful foundations, but **automatic owner-memory use in real voice
conversation is not implemented or active**. Shadow is a development tool;
the approved eventual product outcome is authenticated-owner APPLY, after
delivery/usefulness/privacy and owner-machine qualification.

The attachment supplied on October 20 ends mid-sentence in section 13.3.
Its earlier sections were read; later claims were checked against repository
code and GitHub rather than guessed. The actual checkout is
`C:\Users\gkgaj\Desktop\jarvis_v1`; the new app workspace
`C:\Users\gkgaj\Documents\ChatGPT\Jarvis_V1` was empty at inspection.
The repair branch uses the existing Desktop checkout. Production data,
credentials, camera/microphone and real provider sessions were not accessed.
The handover's hardware table, monthly preference and current machine-setting
claims are owner-reported context, not measurements from this audit. Pinned
LiveKit Agents/Google plugin 1.8.3 and the actual checkout were checked; storage,
provider and identity readiness must be rechecked for live release.

## Reconciliation of decisions and evidence

| Item | Verified disposition | What must not be inferred |
| --- | --- | --- |
| Owner goal | Personal memory, understanding and useful everyday assistance are primary; engineering/self-repair support that experience | Engineering frameworks alone complete the assistant |
| Native architecture | Approved through merged PR #288; reuse canonical stores and existing authority | Repeat architecture approval or replace the core without evidence |
| PR #289 / PI-1A | Twenty fictional event/question cases, separate gold, schema/source checks and paired-annotation contract | Actual paired model answers, semantic scores or live acceptance; manifest reports `NOT_RUN` |
| PR #290 / PI-1B | Read-only canonical-reader coordinator, source/sensitivity/currentness/budget guards and fixture-selector tests | Intelligent free-text relevance selection, trusted spoken-owner attribution or production wiring |
| PR #291 / PI-1C | Opt-in fictional provider probe and offline tests, merged to main | Delivery proven on real Gemini; its original SDK receiver was broken |
| Prior chat / draft PR #287 | Separate native shadow contracts, model diagnostics and 26-case multilingual evidence; draft remains unmerged | Those modules/results are on current main or establish the newer PI implementation's acceptance |
| Hindsight experiments | Reported synthetic retrieval evidence; no selected production owner-data integration | Historical retrieval scores prove natural capture, useful recommendations or safe live release |
| Activation request | Permanent requirement for real automatic context use, not permanent shadow | Skip owner/turn identity, release policy or provider evidence |
| General testing | Owner requested fictional general testing in Hindi, Hinglish, English and broader languages | Require owner-authored examples before proceeding; claim exhaustive all-language fluency |
| Automatic capture / local training | Separate future admission/retention design; local fine-tuning deferred | Read-only activation permits ambient transcript retention or automatic sensitive writes |
| Spending | Preserve existing bounded-provider and no-pre-credit-purchase rules | The handover's approximate monthly preference approves new charges or provider fallbacks |

PRs #288–#291 and #243 were verified merged. Remote main matched the audited
checkout. PR #291's exact source head had a successful Code Quality run;
the merge-SHA workflow query returned no associated runs, which is not itself
a failed check. Fresh local verification is recorded separately below.

Draft #287 remains evidence, not a parallel implementation to merge wholesale.
Its 26-case/78-answer pass observed native lookup timeouts and exact-fact-only
advice limitations. Its English timeout control prevented attributing those
failures to language. Preserve those limitations when reusing the evidence.

## Reproduced defects and repair boundaries

These findings were independently checked with fictional data on the baseline.
Each repair requires an automated regression that fails before the change.
Hardware/provider acceptance remains separate from those regressions.

### A1 — Sensitive owner input reaches durable transport before protection (P1)

Phase-9 pairing marks PIN responses sensitive, but `WorkRuntime.submit_owner_input`
sent raw text to `DBOSWorkExecutionBackend.send_owner_input`. DBOS serialized
the ordinary message before `WorkEngine.apply_owner_input` encrypted its
WorkStore copy. A mocked DBOS boundary received the exact fictional PIN.
Tests checking only the engine bypassed this leaking transport.

Repair must protect at the runtime-to-DBOS boundary using the existing canonical
protection mechanism, bind the response to its work/wait/version, reject stale
or substituted responses, and preserve durable replay without restoring an
already-consumed PIN. No plaintext fallback is acceptable.

The repair encrypts sensitive replies before DBOS using the existing WorkStore
codec and consumes a version/wait-bound envelope atomically. Independent review
then reproduced two remaining bypasses: the raw legacy engine path could feed
an old PIN to a later sensitive wait, and separate store connections could both
consume one protected value. The corrective pass rejects raw sensitive replies
and serializes sensitive SELECT/decode/DELETE in one `BEGIN IMMEDIATE`
transaction, including rollback on decode failure. These checks use fictional
stores and messages; no real PIN or production database was inspected.

### A2 — Cached Hands trust uses stale Windows-session context (P1)

The capability broker hard-coded `windows_session_valid=True` and passed the
original context to permit consumption. Its cache expired by time/close but
did not consult the existing OS session provider. In the synthetic replay an
unavailable Windows provider was polled zero times; a second action reused T2
and the old context. This is distinct from deferred spoken actor attribution.

Repair must revalidate trusted OS evidence before authorization/consumption,
clear cached trust and invalidate approvals/permits on security transitions,
and fail closed on unavailable evidence. Boundary polling alone cannot prove
that a lock/unlock transition did not occur between polls; continuity must not
be assumed from the same session ID. Real Windows transition qualification
remains a release gate.

The repair adds a hidden WTS event monitor with a synchronized monotonic epoch;
session snapshots and permit consumption are bound to that continuity evidence.
Synthetic tests preserve both lock and unlock events between checks. One passive
Windows smoke registered the hidden listener, obtained a healthy epoch/snapshot
and closed it successfully. It performed no lock, Hello or device action, and
does not replace the actual lock/user-switch acceptance test.

### A3 — Default logging persists full conversation text (P1)

`show_transcript` defaulted true; accepted turns were logged verbatim into the
default rotating JSONL handler. Generic event-text redaction did not remove
ordinary private sentences. A temporary-log replay retained the complete
fictional user sentence, contrary to Quality Gates section 6.

Repair turns transcript retention off by default while preserving operational
events. Explicit diagnostic transcript opt-in must remain distinguishable
from ordinary production observability. This audit did not inspect existing
owner logs or assert that no historical transcript files exist.

### A4 — Provider probe calls an absent pinned-SDK method (P2)

The probe called `AgentSession.update_chat_ctx`, absent in installed/pinned
LiveKit Agents 1.8.3. `Agent.update_chat_ctx` exists. After successful startup
the original code would raise `AttributeError` before sending the canary.
The original tests covered offline CLI/evaluator behavior, not execution.

Repair retains the started agent and updates it through the supported API.
Offline execution tests cover startup, context delivery, answer capture,
timeouts/errors and cleanup with actual SDK context/message shapes. This
does not claim a real provider has consumed the context.

### A5 — Repeated identical utterances lose a canonical turn (P2)

Transcript-first deduplication used current text/generation without new
item/activity identity, then marked the new item ID seen. Two distinct
"Open calculator" utterances produced one canonical turn/generation;
the activity epoch advanced to two. A later committed event was discarded,
and Hands' generation guard could suppress the second request.

Repair distinguishes new item IDs/activity epochs from duplicate callbacks,
including the no-ID provider fallback, without duplicating canonical turns.

### A6 — Concurrent explicit remembers create an ambiguous key (P2)

The facade read "no current value" on the reader connection before creating
through the writer. Two concurrent facade calls both succeeded, after which
inspect/correct/forget could not resolve the key. The check and insertion
were not one canonical transaction.

Repair checks absence inside the existing `BEGIN IMMEDIATE` writer transaction
for explicit remembers and maps collisions to `MemoryAlreadyExistsError`.
The general lifecycle still permits legitimate multiple semantic assertions.
Tests cover separate facades, separate writer connections, no losing-source
residue and a usable inspect/correct/forget sequence.

### A7 — Bounded learning scans permanently miss later outcomes (P2)

Repair, promotion, acquisition and compatibility outcome scans selected the earliest `LIMIT`
rows repeatedly without continuation. With three outcomes and bound two,
repeated actual repair-source scans returned only the first two. The
reconciler did not advance beyond them, contradicting missed-outcome recovery.

The repair adds bounded continuation across calls and safe revisiting of failed
normalization/indexing; filtering every previously seen outcome would lose
retries. Continuation is advisory per source instance, resets safely on restart
and wraps to revisit earlier outcomes; it is not a new canonical checkpoint
store. This does not add an automatic production-learning scheduler.

### A8 — Authoritative documents disagree about the current next action (P2)

Current Plan recorded approval/merge at its top but still requested the same
architecture decision at its end. Current Architecture instructed starting
Phase 9 while the ledger accepted 10A; a ledger row independently called 10A
next. The documentation index described already-merged work as draft research.

Reconciliation records the approved native decision, exact foundation limits,
the unmerged #287 evidence boundary and the remaining integration sequence.
Phase 11 remains next only within the supporting engineering program; Step 8
remains next only within the numbered product roadmap. Historical archive
records and North Star goals are preserved.

### Repair evidence map

| Finding | Implementation | Reproducible regression evidence |
| --- | --- | --- |
| A1 | [Input preparation](../../src/jarvis/work/runtime.py), [bound apply and consume](../../src/jarvis/work/store.py), [engine entry](../../src/jarvis/work/engine.py) | [Transport, replay, stale state and concurrent consume](../../tests/test_work_owner_input_transport.py) |
| A2 | [Broker](../../src/jarvis/capabilities/authority_bridge.py), [session evidence](../../src/jarvis/authority/session.py), [hidden listener](../../src/jarvis/authority/windows_session_events.py) | [Authority](../../tests/test_hands_authority.py), [event monitor](../../tests/test_windows_session_events.py), [sanitized passive smoke](../../benchmarks/results/personal_intelligence_reconciliation_2026-10-20/native_session_smoke.json) |
| A3 | [Config](../../src/jarvis/config.py), [example settings](../../.env.example) | [Temporary log retention and voice tests](../../tests/test_livekit_session.py) |
| A4 | [Probe](../../src/jarvis/voice/personal_context_live_probe.py) | [Pinned API, execution, timeout and cleanup](../../tests/test_personal_context_live_probe.py) |
| A5 | [Canonical bridge](../../src/jarvis/voice/livekit_session.py) | [Transcript/commit identity and activity tests](../../tests/test_livekit_session.py) |
| A6 | [Canonical transaction](../../src/jarvis/memory/lifecycle.py), [explicit facade](../../src/jarvis/memory/service.py) | [Two-facade/two-writer lifecycle](../../tests/test_memory_service.py) |
| A7 | [Outcome sources](../../src/jarvis/engineering_learning/sources.py) | [Bounded continuation and retries](../../tests/test_engineering_learning_sources.py), [adapter coverage](../../tests/test_engineering_learning_adapters.py) |
| A8 | [Current Plan](../CURRENT_PLAN.md), [Current Architecture](../CURRENT_ARCHITECTURE.md), [Project State](../PROJECT_STATE.md) | Link and unchanged archive-blob checks below |

## Repository-wide plan alignment

| Area | What source/wiring and existing evidence support | Remaining limits |
| --- | --- | --- |
| Voice/wake/conversation | Substantial production foundations and canonical-turn bridge | Real noise/interruption/mixer behavior and spoken actor isolation are not reaccepted by unit tests |
| Identity/Authority/Hands | Deterministic risk, OPA, Hello, bounded T2, one-time permits and bounded executors | Physical OS continuity/Hello qualification; private spoken-owner attribution is still unproven |
| Personal memory | SQLCipher/DPAPI foundation, explicit lifecycle, provenance and bounded retrieval; A6 restores atomic explicit admission | Automatic admission/injection and full live semantic recall remain deferred |
| Personal intelligence | PI-1A/B policy/evaluation foundations and PI-1C probe | Actual relevance router, LiveContext/identity binding, useful paired answers and APPLY are missing |
| Work/DBOS | Production composition, canonical protected payloads, durable recovery/deliveries, resource-aware reasoning; A1 repairs sensitive transport/consume | Live Postgres/reboot acceptance was not repeated |
| Engineering phases 2–9 | Substantive knowledge/change/router/substrate/source-candidate/promotion/package/acquisition implementations | Phase-9 complete external TV lifecycle remains explicitly unproven |
| Phase 10 | Callable outcome adapters, reconciliation, learning lifecycle and retrieval-integrity boundaries; A7 restores bounded scan progress | No production reconciler caller outside evaluation was demonstrated |
| Phase 10A | Optional control-plane/Work attachment and bounded assisted dispatch | Acceptance explicitly excludes automatic production activation; absence is not an implementation defect |
| Deterministic repair | Bounded R2 recovery, provenance, rolling budgets, process ownership and guardian | R1 vocabulary is not an accepted automatic policy; broad self-evolution remains future work |
| Cost/provider routing | Plan-backed primary plus bounded fallback; C6 Work context defaults shadow; no local Ollama target in production Work pool | Dated local-Qwen checkpoints are historical, not deployment truth; no new spending approved |
| Later product features | Partial Hands foundations are accurately distinguished from formal steps | Notes/reminders, calendar/email, HUD, proactive monitoring and broad autonomy are not completed by this work |

## Verification and limits

Baseline inventory: 964 tracked files, including 846 Python files, 341 Python
test files and 83 Markdown files. The prior complete baseline suite ran
**2,473 passed / 8 skipped**. Ruff lint/format and `pip check` passed.
All 114 checked relative documentation links resolved; all 62 archived/reference
records matched the recorded Git blobs. These checks do not establish line-level
coverage of every source file or repeat historical owner-machine acceptance.

The first combined repair suite passed **2,544 tests / 8 skipped** before the
independent review's two corrective findings. The final corrected suite passed
**2,548 tests / 8 skipped in 303.48 seconds** against an isolated machine profile.
Ruff lint/format (935 files) and `pip check` pass. Independent whole-branch review
reported only the two input findings above; a fresh independent fix reviewer
checked their closure and reran both target modules, **20 passed**, with no
blocking findings. All **155** current relative path links resolve; all **62**
archived/reference Git blobs are unchanged, and both archived native-source
hashes match. Exact-head remote workflow results belong to the resulting
PR, not an inferred local success claim. No real provider call,
device action, production memory mutation, automatic activation or main merge
is part of the audit evidence.

## Remaining path to the owner-facing goal

1. Complete review, tests and protected promotion of the reproduced repairs.
2. Qualify fictional provider delivery on the pinned stack across initial,
   accepted-turn update and tool-result paths, with actual usage/timing.
3. Implement measured free-text relevance selection over canonical evidence
   and trusted owner-turn attribution, preserving absent/restricted/unavailable
   distinctions and source revalidation at release.
4. Run actual matched/held-out answer-use qualification, correction/delete,
   restart, guest, outage, interruption and multilingual scenarios.
5. Wire and qualify the real reversible APPLY/OFF path, obtain owner-machine
   acceptance and enable only for authenticated owner conversations.
6. Design governed natural learning separately; do not divert into fine-tuning,
   new memory servers or additional framework programs without demonstrated need.

The owner need not supply personal examples or unlock another drive for this
sequence. Genuine future owner dependencies are exact protected promotion,
physical/voice observations or unavailable account/provider access, when the
concrete test or change is ready for review.
