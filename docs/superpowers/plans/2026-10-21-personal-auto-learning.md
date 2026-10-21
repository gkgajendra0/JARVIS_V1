# Automatic Personal Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal local JARVIS automatically remember eligible directly stated everyday facts, update them correctly, and use relevant current facts after restart, without per-fact save confirmation.

**Architecture:** Reuse canonical ConversationSession, Authority, SQLCipher/DPAPI, MemoryService/lifecycle and normal personal-context voice tools. Add a scoped owner-session delegation, grounded batch extraction, closed-ID reconciliation and atomic admission with replay/forget protection. Models propose semantics; registered JARVIS policy and source/version-bound child permits control actual access.

**Tech Stack:** Existing Python 3.11+, Pydantic, active-provider structured output (configured Gemini extraction default `gemini-3.5-flash-lite`), SQLCipher/SQLite, Windows Hello/WTS, OPA, LiveKit, pytest and Ruff. No new framework, database, model download or dependency upgrade is planned.

**Spec:** [Approved design](../specs/2026-10-21-personal-auto-learning-design.md), owner reply **“Approve written design”**, 21 October 2026. Approved initial spec commit: `03f29dcb`.

**Status:** executable plan prepared for owner review; implementation has not started. Execution method remains to be selected. Keep work in the owner's existing Desktop checkout, branch `feat/personal-auto-learning-20261021`, honoring the earlier request to use that checkout. Never overwrite unrelated local changes; if parallel edits appear, isolate/reconcile before mutation.

## Global Constraints

- “There is no per-fact confirmation or Hello challenge, and no automatic renewal.”
- “One Windows Hello challenge opens a 15-minute memory session; five minutes without accepted user input ends it sooner.”
- “This is session delegation, not biometric attribution of every speaker.” Private owner-operated conversations are the initial support scope; speaker/ASD shadow scores never grant authority.
- “Wake/sleep does not extend the grant.” Restart, security transitions, manual clear and unhealthy continuity revoke it.
- “No model can create an accepted source, grant, permit, canonical assertion ID or verification status.”
- “Do not relabel extracted candidates OWNER_EXPLICIT.” Automatic facts use OWNER_DIRECT, not invented explicit consent or VERIFIED truth.
- “Raw utterances and source spans remain ephemeral.” Canonical provenance has source/time/digest and `evidence_text=None`.
- First release: standard directly stated owned items, food/response preferences, explicit routines and ongoing goals. Inferences, medical/financial, private/local-only, credentials and third-party profiles are outside automatic admission.
- “32 queued turn receipts, at most 8,000 UTF-8 bytes each”; one inference in flight; at most one extraction plus one reconciliation call per processed turn; no automatic retries.
- “extraction timeout 10 seconds, reconciliation timeout 10 seconds; receipt maximum age 30 seconds.” At most eight proposals and 32 reconciliation candidates.
- At most three preceding accepted USER turns plus the current accepted turn, total 8,000 UTF-8 bytes; reject oversize rather than truncate.
- Context stays at most four facts and 1,800 UTF-8 bytes per answer. Retain current fresh-wake/provider-retirement boundary.
- Explicit forget/private/local-only operations retain action-specific approval; session grant does not satisfy unrelated T3 requirements.
- Physical forget also purges learning payload digests and suppresses automatic learning of that registry facet until explicit re-enable/remember. No forgotten values or reconstructible low-entropy hashes survive in suppression metadata.
- No new paid fallback/account/credit purchase, default production activation, real-owner database migration during tests, ambient recording, full transcript retention or protected-main promotion is authorized by plan execution.
- New semantic acceptance: empirical precision >=0.95; capture recall >=0.80 overall and >=0.70 per language; relevant-use success >=0.85 overall. Publish denominators and uncertainty; any hard permission/lifecycle failure blocks release.

## Review Focus

1. Speech starts before lock/expiry and its model result returns afterward: zero protected lookup/release/write. Tests owned by Tasks 1, 6 and 7.
2. Two same-model vehicles or a plural legacy text facet: never merge/delete the wrong item or overwrite contradictory legacy memory. Task 4.
3. Forget happens while an older source is queued or committing: purge canonical history/index/source/digests and stop re-admission across restart. Tasks 5–7.
4. Wake/provider history closes between acceptance and extraction: eligible source processing survives wake close while grant is valid, but never survives runtime stop or expiry. Tasks 6–8.
5. A fact is related to a question but does not answer its requested relation: do not substitute ownership/value for reason, recommendation provenance or unknown information. Tasks 7 and 9.

## File and interface map

Existing modules are modified at their owning boundary; do not create a parallel DB writer, permission cache, conversation store or context router. New modules:

- `src/jarvis/authority/personal_learning.py`: scoped grant handles, one-use child permits and commit lease.
- `src/jarvis/memory/learning_contracts.py`: immutable internal types plus model-facing proposal schemas.
- `src/jarvis/memory/learning_policy.py`: source/category/importance/span/suppression eligibility.
- `src/jarvis/memory/learning_extractors.py`: active-provider batch extraction/reconciliation transport; reuse existing provider setup and cleanup.
- `src/jarvis/memory/learning_reconciliation.py`: canonical catalog, typed plans and safe entity/scalar resolution.
- `src/jarvis/memory/learning_runtime.py`: bounded runtime-scoped worker.
- `src/jarvis/memory/migrations/0003_personal_learning.sql`: receipts and facet suppression in existing encrypted memory.
- `tests/learning/conftest.py`: fake clock/session/Hello/provider and temporary migrated DB fixtures; never default to owner storage.
- `tests/learning/test_*.py`: meaningful boundary tests enumerated below.
- `benchmarks/personal_auto_learning_v1.json` and separate `_gold.json`: fresh frozen fictional acceptance inputs and labels.
- `tools/research/personal_auto_learning_eval.py`: normal components with explicit fictional-provider opt-in, bounded calls and truthful result states.

Use immutable opaque grant/permit handles backed by issuer registry membership, not caller-constructible authorization booleans. Model Pydantic types do not import or emit those handles. Constructors/types may be organized inside the modules above; the public signatures below are binding.

## Verification conventions

From `C:\Users\gkgaj\Desktop\jarvis_v1`, use `& .\.venv\Scripts\python.exe -X utf8 -m pytest ...`. In every code task: write the named failing test(s), observe a behavior/import failure attributable to the missing feature, implement the smallest change, rerun the task tests and indicated regressions, then commit only that task's files. Do not infer a RED result from an unrelated environment failure. No live network, real Hello or owner DB is needed for unit/integration tests.

At execution start verify branch/status, Python dependency health and the full existing suite once. Record baseline failures before changes. No dependency install merely for setup: the working environment already exists.

---

### Task 1: Scoped personal-learning delegation and exact child permissions

**Files:** create `authority/personal_learning.py` under `src/jarvis` and `tests/learning/conftest.py`; modify `src/jarvis/capabilities/authority_bridge.py`, `src/jarvis/capabilities/runtime.py`, `src/jarvis/authority/types.py`, `src/jarvis/authority/approval.py`, `src/jarvis/authority/service.py`, `src/jarvis/authority/policy.py`, `policies/step3_authority.rego`; test `tests/learning/test_authority.py`, `tests/test_hands_authority.py`, `tests/test_opa_policy_adapter.py`.

**Interfaces:**
- Produce `PersonalLearningAuthority`, backed by the existing broker, session monitor, approval service, permit registry and audit.
- `open(runtime_id: str, provider: str) -> LearningGrantHandle`: direct local launch intent only; fresh Hello approves code-owned policy digest `personal-learning-v1`.
- `validate(grant: LearningGrantHandle) -> LearningSessionState`; `observe_accepted_input(grant: LearningGrantHandle, turn_id: str) -> None`; `revoke(grant: LearningGrantHandle, reason: str) -> None`.
- `issue_child(grant: LearningGrantHandle, binding: LearningActionBinding) -> LearningPermitHandle`; `commit_scope(permit: LearningPermitHandle) -> ContextManager[None]` and `validate_read(permit: LearningPermitHandle) -> None`.
- `LearningActionBinding` is an authority-owned immutable value: operation, source receipt ID, target IDs/expected versions, payload SHA-256, policy version and suppression epoch. Caller data is bound, not treated as proof.
- `LearningSessionState` contains `status` (`active`, `expired`, `revoked`, `denied`) and bounded reason/expiry metadata. Test fixtures `authority` and `clock` use fake Hello/WTS and monotonic time; `clock.advance(seconds)` is explicit, with no real sleeps.
- Add `ApprovalMethod.DELEGATED_POLICY` and nullable parent-delegation identity on ApprovalRecord. Only `ApprovalService.grant_delegated(..., grant: LearningGrantHandle)` may issue it after the issuer registry validates scope/binding; generic `grant(method=DELEGATED_POLICY)` rejects just as generic strong-verifier granting does. The existing approval/permit registries remain authoritative, not a side-channel execution permit.

- [ ] Write failing fake-clock tests with the following explicit expectations:

```python
def test_absolute_expiry_is_not_renewed_by_input(authority, clock):
    grant = authority.open("runtime-A", "gemini")
    for index in range(4):
        clock.advance(200)
        authority.observe_accepted_input(grant, f"turn-{index}")
    clock.advance(100)
    assert authority.validate(grant).status == "expired"
```

Also test idle expiry at 300 seconds, absolute expiry at 900 seconds, denied Hello, stale WTS generation after lock/unlock, fabricated/copied/other-runtime handles, duplicate child consumption, payload alteration, provider change and unrelated Hands T3 action. A repeated already-seen turn ID must not extend idle time; T2 cache must not open this grant without fresh Hello.
- [ ] Pin the local Hello material summary: standard eligible categories, automatic read/write during the private delegated session, 900-second absolute/300-second idle limits and no per-speaker identity guarantee. No raw owner memory appears in that opening summary; denial grants nothing.
- [ ] Run `pytest -q tests/learning/test_authority.py`; confirm expected RED.
- [ ] Register the exact `memory:personal_learning` operations `open`, `read`, `admit`, `close` in code-owned policy metadata. Opening uses the existing fresh-owner path; read/admit require the issuer-validated delegation binding. Model-supplied policy fields are rejected. Extend OPA input/decision contract only for this capability; risk class for arbitrary writes stays unchanged. Audit IDs/status/digests, not raw facts.
- [ ] Make delegated child proposals SYSTEM-origin, not fabricated DIRECT_USER per-action intent. Their explicit-level approval is derived from the registered strong-approved policy scope and exact child fingerprint. AuthorityService validates that specialized method only for standard memory read/admit; OPA rules for that capability are mutually exclusive with generic rules, avoiding conflicting decision outputs. The existing persistent-write hard floor is not lowered, and delegated approval cannot satisfy STRONG or any other capability's EXPLICIT requirement. Test bare serialized parent IDs, altered policy digests, wrong operation and direct generic grant attempts as denied.
- [ ] Implement handles, expiry, source-input replay guard, child lease validation and revocation under the broker's existing synchronization. Native session/continuity validation is required at child use and transaction boundaries; document observable event ordering rather than claiming OS changes and SQL COMMIT are one physical atomic event.
- [ ] Run task tests plus `tests/test_hands_authority.py tests/test_authority_security_edges.py tests/test_opa_policy_adapter.py tests/test_personal_context_runtime.py`; expect all PASS with no real Hello.
- [ ] Commit `feat: add scoped personal-learning authority`.

### Task 2: Grounded batch contracts and selective learning policy

**Files:** create `memory/learning_contracts.py`, `memory/learning_policy.py`; extend `tests/learning/conftest.py`, add `tests/learning/test_policy.py`; preserve existing `memory/candidates.py` contracts.

**Interfaces:**
- `AcceptedLearningSource` contains runtime/session/turn IDs, accepted generation/activity epoch, monotonic accepted time, source digest and bounded ephemeral accepted USER turns. Only the canonical runtime binder registers a source receipt.
- `EvidenceSpan(turn_id: str, start: int, end: int)` uses zero-based Python Unicode-code-point indices, end-exclusive; no UTF-8-byte offset confusion.
- `LearningCandidate` Pydantic schema: `category` (`owned_item`, `food_preference`, `response_preference`, `routine`, `goal`), `intent` (`new`, `change`, `correction`, `retraction`, `transient`, `none`), directly supported value fields, spans, sensitivity, temporal hint and diagnostic confidence. `LearningBatch(candidates: list[LearningCandidate])` maximum eight.
- `LearningPolicy.evaluate(source: AcceptedLearningSource, candidate: LearningCandidate, suppressed_categories: frozenset[str]) -> LearningEligibility`; eligibility is `eligible`, `transient` or `drop` with reason only, never a permit.
- Define the strict model-facing catalog/closed-resolution schema here, using Task 4's fields, so Task 3 can import it before semantic reconciliation is implemented. Model-facing schemas do not contain grant/permit handles. Add a `learning` temporary-DB test harness fixture with `service`, `authority`, `plan`, `new_permit()` and async `canonical_effect_count()`; the count queries canonical create/change effects for that harness source, excluding receipt rows.

- [ ] Add RED tests:

```python
def test_invented_value_cannot_be_admitted(source, candidate, policy):
    assert (
        policy.evaluate(
            source("Mere paas City hai"),
            candidate(value="Creta", span=(10, 14)),
            frozenset(),
        ).status
        == "drop"
    )
```

Pin exact multilingual spans, ninth-candidate rejection, aggregate 8,001-byte input rejection, private/secret/out-of-scope categories, quoted/uncertain/transient claims, per-turn “do not remember” veto and confidence=1.0 without evidence. Previous turns alone cannot create a new write; at least one current accepted-turn span must establish the asserted relation/change.
- [ ] Run `pytest -q tests/learning/test_policy.py`; confirm RED.
- [ ] Implement strict Pydantic extra-field rejection, source receipt validation and code-owned category/scalar-facet registry. Use existing explicit-control and secret prefilters. Exact spans prove grounding, not ownership semantics; do not implement a new Hindi keyword classifier or confidence threshold as semantic authority.
- [ ] Run task tests and `tests/test_memory_candidates.py tests/test_memory_candidate_extractors.py tests/test_memory_service_authority.py`; expect PASS and unchanged explicit-source requirements.
- [ ] Commit `feat: define grounded automatic-learning contracts`.

### Task 3: Active-provider structured batch extraction

**Files:** create `memory/learning_extractors.py`; reuse `src/jarvis/memory/extractors.py` provider setup, `src/jarvis/ai_provider.py`; test `tests/learning/test_extractors.py`.

**Interfaces:**
- Protocol `LearningExtractor.extract(source: AcceptedLearningSource) -> Awaitable[LearningBatch]`.
- Protocol `LearningResolver.resolve(source: AcceptedLearningSource, batch: LearningBatch, catalog: LearningCatalog) -> Awaitable[LearningResolutionBatch]` (catalog/resolution types produced in Task 4).
- `build_learning_adapters(provider: str, model: str) -> tuple[LearningExtractor, LearningResolver]`; use existing role-model resolution and credential policy, no cross-provider fallback.

- [ ] Write fake-provider RED tests asserting one configured native structured call, schema validation, `store=False`, model family consistency, original-script spans, no labels/expected IDs/authority handles in model input, sanitized failure state and client cleanup. Two vehicles in one source must permit two proposals; a quoted example is not a granted source.
- [ ] Run `pytest -q tests/learning/test_extractors.py`; confirm RED.
- [ ] Implement batch prompt/schema and native Gemini/available active-provider adapter using existing SDK conventions. Resolver emits only closed catalog selections or `new`/`uncertain`; it cannot invent IDs. Catch/translate provider errors without logging prompt/response bodies. Runtime owns 10-second timeouts and single-attempt policy, not hidden SDK retry multiplication; explicitly configure/verify transport attempt count.
- [ ] Run task tests plus existing extractor/provider-policy tests; inspect captured mock requests for no evaluator data or private-catalog material.
- [ ] Commit `feat: add provider-native learning extraction adapters`.

### Task 4: Entity reconciliation and scalar identity

**Files:** create `memory/learning_reconciliation.py`; extend authorized catalog query in `src/jarvis/memory/query.py`; test `tests/learning/test_reconciliation.py`.

**Interfaces:**
- `LearningCatalog` is an immutable authorized snapshot of at most 32 current eligible standard records: opaque IDs, exact versions, category, source authority and bounded normalized fact values.
- `LearningResolutionBatch` supplies a closed ID or `new`/`uncertain` for each candidate; relationship/temporal intent remains a proposal. Its model-facing shapes were defined in Task 2; this task implements meaning, authorization and canonical resolution.
- `LearningReconciler.catalog(source: AcceptedLearningSource, batch: LearningBatch, grant: LearningGrantHandle) -> Awaitable[LearningCatalog]` validates grant before protected reads.
- `LearningReconciler.plan(source, batch, catalog, resolutions) -> LearningPlan`; typed parameters are those four contracts. `LearningPlan` holds a tuple of `PlannedLearningMutation` with action (`create`, `change`, `correct`, `retract`, `noop`), exact category/entity/facet, expected assertion ID, validated draft and source reference. Only server-generated new entity IDs/predicates are allowed.

- [ ] RED tests: two different vehicles create two independent stable identities; a later sale targets only one; same-model ambiguous vehicles yield no mutation; exact duplicate is `noop`; version mismatch/unknown ID is rejected; Hindi semantic duplicate fixture cannot be resolved merely by lowercasing; contradictory legacy `vehicles` TEXT is preserved without guessed migration. Existing scalar preference uses its actual canonical predicate, not an invented alias.
- [ ] Run `pytest -q tests/learning/test_reconciliation.py`; confirm RED.
- [ ] Implement standard-only authorized catalog, exact/eligible retrieval reuse and closed-ID resolution. Stable scalars: `diet_preference`, `response_language`, `response_style`; existing uniquely resolved legacy scalar names remain their actual predicates. Entities use `owned_item_<uuidhex>`, `routine_<uuidhex>`, `goal_<uuidhex>`. Their JSON value includes `category`, `label`, directly supported attributes and applicable current status; normalization does not add facts. For ownership ending, make current status non-owned and preserve time-scoped history; context must not describe it as currently owned.
- [ ] Run task tests plus current personal-context/retrieval/lifecycle tests. Reconciliation never reads private/local-only or inferred records through a broad default eligibility.
- [ ] Commit `feat: reconcile automatic facts against canonical identities`.

### Task 5: Atomic admission, migration and replay protection

**Files:** add `memory/migrations/0003_personal_learning.sql`; modify `memory/lifecycle.py`, `memory/service.py`, `memory/runtime.py`, migration expectations in their existing tests; add `tests/learning/test_admission.py`, `tests/learning/test_migration.py`.

**Interfaces:**
- `MemoryService.admit_learning(plan: LearningPlan, permit: LearningPermitHandle) -> Awaitable[LearningAdmissionResult]` is the sole public automatic-write facade. Result contains committed/noop/stale/denied status and canonical IDs, no raw utterance. `MemoryRuntime.bind_learning_authority(authority: PersonalLearningAuthority) -> None` binds the real issuer once during trusted runtime composition; default is no issuer and rebinding is rejected. A per-call authority-like Python object cannot make a supplied plan authoritative.
- `MemoryLifecycleService.apply_learning_batch(plan, permit, authority) -> Awaitable[LearningAdmissionResult]` uses the existing writer and one transaction; exact plan types above apply, and the facade supplies only its bound authority.
- Migration tables: `personal_learning_receipt` (runtime/source-turn/candidate/policy identity, category, payload digest, source ID, target ID), unique on `(source_turn_id,candidate_ordinal,policy_version)`; and `personal_learning_suppression` (registry category primary key, epoch, suppressed Boolean, timestamp). Retain no raw text or forgotten value hash in suppression. Each automatically admitted candidate has a distinct canonical source ID so forgetting one item need not retain its evidence digest in another item's shared source.

- [ ] RED integration test:

```python
async def test_replay_has_one_canonical_effect(learning):
    first = await learning.service.admit_learning(learning.plan, learning.new_permit())
    second = await learning.service.admit_learning(learning.plan, learning.new_permit())
    assert first.status == "committed"
    assert second.status == "noop"
    assert await learning.canonical_effect_count() == 1
```

Define these fixtures in `tests/learning/conftest.py` using temporary migrated SQLite/fake authority. Also pin all-or-nothing two-item commit, stale target after explicit correction, scope epoch race, rolled-back receipt, invalid permit, owner-direct provenance and two writer connections racing the same replay key.
- [ ] Run task tests; confirm RED.
- [ ] Refactor existing lifecycle transaction bodies into connection-local helpers callable within one outer `BEGIN IMMEDIATE`; do not nest public async transactions or create another writer. Existing create/correct/change/retract/forget paths keep regression behavior. Acquire authority commit lease, check source/epoch/version and uniqueness, apply all mutations and receipts, revalidate, then commit. Rollback restores receipts and canonical data together. A byte-identical replay is a no-op; same replay key with a changed digest is rejected.
- [ ] Apply new migration only on temporary test DBs. Verify prior migration hashes unchanged, schema 2→3 preserves explicit facts/FTS/embeddings, missing/corrupt ledger rejects, failed migration rolls back. Update packaged-smoke expectations to version 3 without rewriting historical acceptance evidence.
- [ ] Run new tests plus `tests/test_memory_lifecycle.py tests/test_memory_service_authority.py tests/test_memory_migrations.py tests/test_memory_database.py`. Expect PASS; no owner DB opened.
- [ ] Commit `feat: commit automatic learning atomically with replay guards`.

### Task 6: Forgetting, suppression and pending-source invalidation

**Files:** modify `memory/service.py`, `memory/lifecycle.py`, relevant query/index cleanup, `voice/memory_tools.py`; add `tests/learning/test_forgetting.py`.

**Interfaces:**
- `MemoryService.learning_suppression() -> Awaitable[LearningSuppressionSnapshot]` (category→epoch/state only).
- `MemoryService.reenable_learning_category(category: str, explicit_source: MemorySource, commit_guard: Callable[[], None]) -> Awaitable[None]` requires existing exact direct explicit approval; no model-only/session auto re-enable.
- Existing `MemoryService.forget_exact` / voice `forget_memory` calls additionally invalidate relevant learning source epochs, purge entity lineage/receipt digests and set category suppression in their transaction. `PersonalLearningRuntime.invalidate_sources(category: str | None, turn_id: str | None) -> None` is supplied in Task 7; do not retain old values to match later.

- [ ] RED tests: after learning two vehicles and one change, forget one and reopen the DB; no targeted current/history/source/FTS/embedding/receipt digest survives, the second vehicle remains readable, and automatic vehicle learning is suppressed. Queue an older turn before forget and finish it afterward: zero re-admission. A forged/unapproved re-enable must fail. Never re-save forgotten content from an old provider result.
- [ ] Run `pytest -q tests/learning/test_forgetting.py`; confirm RED.
- [ ] Extend the existing physical-forget facade to target the resolved entity lineage, not unrelated entities sharing words. Do not broaden arbitrary explicit scalar forget into global deletion. Bind suppression/receipt cleanup and physical forget to the same authorized transaction; discard queued receipts via the category epoch. Keep explicit forget approval and source-authority checks intact.
- [ ] Run task tests and `tests/test_memory_lifecycle.py tests/test_memory_service_authority.py tests/test_memory_tools.py tests/test_memory_intent_repair.py`; expect PASS. Inspect temporary DB rows and derived indexes, not only tool success flags.
- [ ] Commit `feat: prevent automatic relearning after forget`.

### Task 7: Runtime-scoped bounded background worker

**Files:** create `memory/learning_runtime.py`; test `tests/learning/test_runtime.py`.

**Interfaces:**
- `PersonalLearningRuntime(authority, service, extractor, resolver, reconciler, *, clock, status_observer)` consumes Tasks 1–6 contracts; one owner per production runtime.
- `bind(conversation: ConversationSession, grant: LearningGrantHandle) -> Callable[[ConversationTurn], None]` returns a canonical accepted-turn observer that snapshots a registered `AcceptedLearningSource`.
- `observe_turn(conversation, turn, grant) -> None` is nonblocking; `invalidate_sources(category=None, turn_id=None) -> None`; `status() -> LearningRuntimeStatus`; `close() -> Awaitable[None]`.
- `LearningRuntimeStatus` exposes mode/session/queue/count/reason fields only. `MemoryRuntime.service` remains the canonical write owner.

- [ ] RED tests: queue cap=32, one inference in flight, timeout=10 seconds each, receipt expires at 30 seconds, oversize source rejected, no hidden retry, accepted callback never awaits provider/DB, and duplicate turn input does not refresh idle time. Closing a wake/provider session does not delete an accepted process receipt; runtime close, lock/expiry or privacy veto cancels/discards it. New accepted turn with “don't remember this” invalidates that turn before cloud extraction.
- [ ] Run `pytest -q tests/learning/test_runtime.py`; confirm RED.
- [ ] Implement bounded queue and one worker task, native asyncio timeouts/cancellation, no task per audio frame, validated source windows and pre/post-await grant checks. Use freshest suppression epoch before resolution/commit. Empty-catalog new facts may resolve deterministically with no second model call; do not equate an empty *denied/unavailable* catalog with absence. Disable the old shadow extractor for turns already handled by this runtime to avoid double calls.
- [ ] Run runtime and admission tests with fake time/providers and existing candidate-runtime regressions; expect PASS and no dangling tasks. Status logs contain no facts, spans, predicates or raw provider exception bodies.
- [ ] Commit `feat: run bounded automatic learning behind canonical turns`.

### Task 8: Grant-backed context release and normal local launch

**Files:** modify `config.py`, `voice/production_runtime.py`, `voice/canonical_active_speaker_runtime.py`, `voice/personal_context.py`, `voice/agent.py`, `voice/memory_tools.py`, relevant audio/authority composition; add `tests/learning/test_production.py`, `tests/learning/test_context.py`; extend existing config/CLI tests.

**Interfaces:**
- `JarvisConfig.personal_learning_mode: str = "off"` (`off`/`apply`), environment `JARVIS_PERSONAL_LEARNING_MODE`; CLI `--personal-learning {off,apply}`. Apply implies memory enabled, personal-context apply and transcripts disabled. Explicit conflicting `--personal-context off` + learning apply is an argument error, not silent mode override.
- `CapabilityRuntime.open_personal_learning(runtime_id: str, provider: str) -> LearningGrantHandle`, `close_personal_learning(grant) -> None`; local launch/control calls only, not a model tool that can self-open/re-enable sessions.
- `PersonalContextSession(..., learning_authority=None, learning_grant=None)` optionally derives source/question-bound standard read permits from the grant; legacy exact mode is unchanged.

- [ ] RED tests: normal launch APPLY creates exactly one runtime worker and one session-open challenge; OFF creates neither. Multiple eligible facts and later fresh wakes within grant generate no more save/read Hello challenges. Expired/denied grants do not reopen automatically. Scalar and per-entity current facts are readable; ended ownership is not described as current. Relevant-context source versions and private audio are guarded through interruption, change/forget and epoch revocation.
- [ ] Add RF5 tests with known owner bike paired to “why did I buy it?” and an unrelated programming question: no unsupported personal answer may be synthesized from successful related-fact retrieval. Add bounded standard fact payload fixtures for Hindi/Hinglish and truthful absent/unavailable results.
- [ ] Run new tests; confirm RED.
- [ ] Wire grant lifecycle once at production runtime startup, bind the canonical memory facade to that issuer once, attach observer at each canonical bridge, and close the worker on actual runtime shutdown. Preserve existing provider session retirement after a personal answer; keep the grant across fresh wakes without extending its absolute lifetime. Prompt data remains evidence, not instruction. Explicit memory tools retain accepted authorizations; ordinary declarations are observed by the learning pipeline instead of asking the model to call explicit `remember_memory`.
- [ ] Run new tests plus `tests/test_personal_context_runtime.py tests/test_personal_context_production.py tests/test_memory_intent_repair.py tests/test_memory_tools.py tests/test_ai_provider_policy.py tests/test_config.py tests/test_memory_candidate_runtime.py`. Verify CLI help in installed editable environment. No real microphone, Hello, provider or owner database for this step.
- [ ] Commit `feat: integrate automatic personal learning in normal Jarvis voice`.

### Task 9: Fresh end-to-end quality, cost and normal-app acceptance

**Files:** add `benchmarks/personal_auto_learning_v1.json`, `_gold.json`, `tools/research/personal_auto_learning_eval.py`, `tests/learning/test_eval.py`; add dated `docs/research/PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-21.md` and eventual owner acceptance record (use actual later date if needed).

**Interfaces:** runner `run_learning_eval(inputs_path: Path, gold_path: Path, output_dir: Path, *, allow_provider: bool = False, max_provider_attempts: int = 270) -> LearningEvalSummary` and CLI `--allow-fictional-provider-run`. Default is zero-network contract checking. Output has completed/unavailable counts, actual provider attempts/tokens, authoritative write/read results and held-out advice review. Fake/stub paths never count as model-quality acceptance.

- [ ] Freeze 90 fresh fictional episodes (30 EN, 30 HI, 30 Hinglish) before provider execution: each language has 15 admissible create/change/correction episodes, five duplicate/no-op episodes, five quoted/third-party/uncertain/transient exclusions and five lifecycle/irrelevant-or-unknown question episodes. Include two items, same-model ambiguity, legacy text and forget/restart. Persist input/gold file SHA-256s; labels/expected IDs never reach extractor/resolver/answer prompts. Earlier retired datasets supply failure *categories*, not copied acceptance text or tuning data.
- [ ] Freeze a 30-question answer-use subset (10 per language: six relevant, two irrelevant, two unknown-relation) and obtain context/no-context answers only for this subset. All 90 episodes still verify canonical effects and context eligibility. Maximum planned calls are 180 learning calls plus 60 answer calls, with the hard 270-attempt cap covering any authorized transport preflight; do not quietly expand to 90 paired-answer questions or repeat calls for a better score.
- [ ] RED runner tests: gold leakage rejected, fixed manifest hash mismatch aborts, provider unavailable/timeouts not scored as correct abstentions, partial runs never pass full acceptance, count cap enforced across all inference components and no writes outside temporary fictional DBs. Paired-answer review uses shuffled arm labels and frozen rubric; agent-authored judgment is identified, never sold as human acceptance.
- [ ] Run `pytest -q tests/learning/test_eval.py`; confirm RED, then implement and get PASS.
- [ ] Execute the full deterministic suite, Ruff format/lint and dependency check once after integration. Run official Windows SQLCipher/DPAPI/Hello packaging and applicable CI checks on the exact candidate. Apply migrations only to fictional copies in this qualification.
- [ ] Run the fictional provider cohort only through the existing authorized provider/quota path, no new paid fallback or purchased quota. Enforce the 270-attempt total cap, no retries; stop truthfully if existing provider resources do not permit completion. Publish completed/failed counts, precision/recall/per-language denominators, Wilson intervals, actual advice success, token usage and baseline/enabled latency/resource distributions. Added accepted-turn callback p95 target <=10 ms in the same controlled harness. A blocked cohort is unfinished acceptance, not a reason to keep retesting old vendors.
- [ ] Ask for whole normal-app owner acceptance only when software/provider checks pass: run local JARVIS with the new mode, supply fictional facts, restart, ask relevant questions, change one fact and forget it. Record actual spoken results and session UX; no isolated mic demo or owner-written corpus is required. If owner observation is not yet available, clearly mark candidate software-ready with acceptance pending, not feature complete.
- [ ] Commit qualification evidence with exact candidate SHA and reproducible commands; do not claim all-language or guest-safe generalization.

### Task 10: Review, documentation and governed promotion

**Files:** update `docs/CURRENT_PLAN.md`, `CURRENT_ARCHITECTURE.md`, `PRODUCT.md`, `PROJECT_STATE.md`, `ROADMAP.md`, `README.md`; add `docs/research/PERSONAL_AUTO_LEARNING_ARCHITECTURE_DECISION_2026-10-21.md` as the durable subordinate decision record (there is no current standalone ADR directory); update normal launch/OFF instructions and acceptance references.

- [ ] Self-review the entire diff against this plan/spec and all five Review Focus classes. Get the selected workflow's independent code review before claiming readiness; investigate actionable findings and add a real regression before a fix. Review memory-source binding, OPA scope, receipt construction, lock/commit ordering, physical deletion and provider-history/audio revocation explicitly.
- [ ] Reconcile documentation to actual verified behavior. Mark unrun provider/owner checks pending, keep broader CAP-053 partial as appropriate, and retain automatic learning OFF by default until owner-governed activation. Record the private-channel delegation limitation, session limits, OFF command, migration compatibility and category suppression after forget.
- [ ] Verify documentation links, diff whitespace, final applicable tests and exact-head CI. Do not rerun full suites without a new change/failure/reason after they pass. Prepare a reviewable draft PR if authorized execution reaches that point, attach its URL to the chat, and state exact validation/limitations.
- [ ] Protected promotion requires the owner's explicit approval of the checked candidate. Do not reuse the earlier #292–#294 merge approval for this permission-expanding feature.
- [ ] Rollback: disable learning mode and revoke all grants; continue using accepted explicit memory and context mode. Do not run an older schema-2 binary against a schema-3 DB or downgrade/delete owner data. Code rollback needs a version-3-compatible release or separately reviewed encrypted backup restoration.

## Plan self-review record

- Spec coverage: session/revocation (1), batch grounding/selectivity (2–3), identities/temporal reconciliation (4), atomicity/migration/replay (5), physical forget/suppression (6), bounded process lifecycle (7), actual launch/context/audio (8), semantic/usefulness/resource/owner evidence (9), review/status/promotion/rollback (10).
- Types are defined at their producing task; Task 2 defines model-facing catalog/resolution schemas for Task 3's adapters, and Task 4 implements their authorization/canonical semantics. Temporary test harnesses are produced before their consuming tasks.
- No old corpus is designated fresh acceptance; no incomplete/failed provider run is counted as a quality pass.
- No external memory service is a hidden prerequisite. New research is justified by a specific measured gap and is bounded to that gap.
- No product code is changed by writing/approving this plan. Before execution, the owner reviews this plan and selects native or subagent-driven execution as required by the planning workflow.
