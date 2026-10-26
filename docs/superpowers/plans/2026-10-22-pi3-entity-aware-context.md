# PI-3A Question-Bound Personal Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let ordinary personal questions obtain the right current saved facts through normal JARVIS voice tools, without manual memory-search instructions or per-fact confirmation.

**Architecture:** Keep canonical SQLCipher, Conversation, Authority and the configured realtime model. Add a deterministic, locally resolved question/scope query, bounded evidence projection and one shared per-answer release ledger. Preserve existing explicit mutations and context-only behavior.

**Tech Stack:** Python >=3.11; existing Pydantic 2.13.5, SQLite/SQLCipher reader workers, LiveKit agents/google 1.8.3, google-genai 2.22.0, pytest/pytest-asyncio and Ruff 0.16.5. No dependency changes.

**Spec:** [Approved written design](../specs/2026-10-22-pi3-entity-aware-context-design.md), approved by the owner as “Approve written PI-3A design.”

**Status / execution:** OWNER-APPROVED plan (22 October 2026): “Approve plan — continue Native implementation.” Tasks 1-7 software-verified; the three Important final-review repairs passed regression and full-suite checks. Dependent draft PR #296 is published; hosted checks and whole-app acceptance remain separate. Preserve the owner's Native execution selection; do not ask for the method again. Base is design commit `22e4ec7e`, on top of unmerged PI-2 candidate `6f52b8ea`; PI-3 implementation is on this candidate; actual-model/normal-app acceptance remains pending. Work in the existing `C:\Users\gkgaj\Desktop\jarvis_v1` checkout, on a non-main branch; do not create another checkout against the owner's declared preference.

## Global Constraints

- New tool only in **personal-learning APPLY**; context-only APPLY keeps its accepted catalog/read path, and OFF exposes no new read tool. Installation defaults and saved machine settings remain unchanged.
- Existing permission window: maximum 15 minutes, five-minute idle expiry, no automatic renewal; current canonical question only, existing source/turn/session/epoch binding, Windows continuity revocation and one-answer private-history retirement.
- Exact scopes: `owned_item.vehicle`, `owned_item.device`, `owned_item.other`, `food_preference`, `response_preference`, `routine`, `goal`; code-owned registry is authoritative.
- One to four requests; optional nonempty exact current-question `target_quote`, maximum 256 UTF-8 bytes, nonscalar scopes only. No coercion, unknown fields, arbitrary SQL/identity/history, inferred labels or fuzzy/cross-script alias matching.
- Maximum 32 current scoped assertions; at most four released assertions; entire compact UTF-8 JSON `facts` array at most 1,800 bytes, including metadata. No clipping, first-four selection, partial multi-scope result or metadata-only profile release.
- At most three evaluations before successful release; invalid attempts count. Only identical same-path successful requests can replay after validation; the other read path cannot release after the first path has released.
- Preserve current/source eligibility and correction/forget/suppression invalidation, including requested-scope membership/version changes, before data return and audio release. Suppression controls learning, not a new blanket read prohibition.
- No new learning/write path, schema migration, standing profile, raw transcript persistence, model/service/download or additional HTTP reasoning call. No provider inference run, billing/account/model change, local activation or protected merge authorized by plan approval.
- Software tests, actual-model behavior, normal-app owner acceptance and protected promotion remain separate evidence states. Preserve PI-2 deferred results rather than converting them into passes.

## Review Focus

These initially easy-to-miss cases are pinned to the named tasks below:

1. A writer commits between the record and suppression reads: the projection must use one coherent database snapshot (Task 2).
2. Unicode-equivalent labels or multiple current records identify the same target: clarify rather than resolve by order (Task 3).
3. A legacy read and new query race: only one path can release, with no cumulative fact/metadata expansion (Task 4).
4. An unselected candidate changes and makes a previously unique target ambiguous: queued old audio must be cleared (Task 5).
5. APPLY instructions survive while the corresponding tool is absent or expires: never advertise an unavailable tool or reopen its session (Task 6).

## File and interface map

| File | Responsibility |
| --- | --- |
| Create `src/jarvis/memory/personal_context_projection.py` | Strict query models, immutable scoped snapshot/projection contracts, deterministic local selection, projection serialization and scope signature; no runtime/Authority/provider ownership. |
| Modify `src/jarvis/memory/query.py` | One coherent scoped-current/suppression read, reusing existing registration/eligibility query. |
| Modify `src/jarvis/memory/retrieval.py` | Public snapshot facade over the canonical reader; voice never reaches into `_worker`. |
| Modify `src/jarvis/voice/personal_context.py` | Query orchestration, serialization, shared release state, guard integration and new tool wrapper. Keep selection algorithm in the focused memory module. |
| Modify `src/jarvis/voice/agent.py` | Mode/tool-aware instructions; explicit mutations retain old target-resolution route. |
| Tests listed per task | Pure contract cases plus real temporary canonical DB, normal runtime and audio-chain regressions. No owner DB or cloud calls. |
| Documentation in Task 7 | Current state, test/latency evidence, enablement and whole-app acceptance protocol. |

All paths below are relative to the Desktop repo. Run commands there in PowerShell. `PY` in this plan means `.\.venv\Scripts\python.exe -X utf8`; expand it literally when running, not as a new global environment variable. Commits use the repo's established identity if Git requires it.

---

### Task 1: Strict current-question query contracts

**Files:** Create `src/jarvis/memory/personal_context_projection.py`; create `tests/learning/test_context_query_contracts.py`.

**Interfaces:**
- Consumes the existing `jarvis.personal_learning_scope.SUPPRESSION_KEYS` registry.
- Produces frozen strict Pydantic `PersonalContextRequest(scope_key: Literal[the seven registered keys], target_quote: str | None = None)` with extra fields forbidden. An omitted target has internal value None; explicitly supplied null, empty/whitespace-only strings and coercions are invalid.
- Produces `parse_context_requests(requests: object, *, question: str) -> tuple[PersonalContextRequest, ...]`; accepts a list of strict raw objects or already validated request models, raises ValueError on invalid input. Quote grounding is exact before Unicode matching; no trimming changes the grounding input. Reject scalar targets and duplicate `(scope_key, target_quote)` pairs.

- [x] **Step 1 — Write failing contract tests.** Pin one/four accepted requests versus zero/five, all seven registry keys, extra keys, boolean/list/integer/coerced values, explicit null, duplicate requests and scalar targets. Pin original-script quotes, absent quotes and byte-based boundaries, including multibyte Hindi. Representative assertions:

```python
assert (
    parse_context_requests(
        [{"scope_key": "owned_item.vehicle"}], question="Meri gaadi?"
    )[0].target_quote
    is None
)
with pytest.raises(ValueError):
    parse_context_requests(
        [{"scope_key": "food_preference", "target_quote": "food"}], question="food?"
    )
with pytest.raises(ValueError):
    parse_context_requests(
        [{"scope_key": "owned_item.vehicle", "target_quote": "सिटी"}],
        question="Meri City?",
    )
```

- [x] **Step 2 — Observe RED.** Run `PY -m pytest tests/learning/test_context_query_contracts.py -q`; expect collection/import or missing-interface failure, not an unrelated fixture/environment failure.
- [x] **Step 3 — Implement the contracts/parser.** Keep the seven-key tool schema equal to the registry using an explicit equality test; use existing Pydantic, with custom UTF-8/grounding checks. Deterministic validation errors stay local and must not be copied into provider responses.
- [x] **Step 4 — Observe GREEN.** Run the same test command; require all cases passing.
- [x] **Step 5 — Commit** as `feat(context): define strict question-bound scope requests` and record RED/GREEN evidence in this plan's execution ledger.

### Task 2: Canonical coherent snapshot and public read facade

**Files:** Modify `src/jarvis/memory/personal_context_projection.py`, `src/jarvis/memory/query.py`, `src/jarvis/memory/retrieval.py`; create `tests/learning/test_context_query_snapshot.py`.

**Interfaces:**
- Produces frozen `ScopedContextSnapshot(entries: tuple[tuple[SemanticAssertionRecord, str], ...], suppression: tuple[tuple[str, int, bool], ...])`. Suppression entries use sorted registry keys, with absent rows represented by epoch 0 / false.
- Produces `CanonicalMemoryReader.learning_context_snapshot() -> ScopedContextSnapshot` and `SemanticRetrievalService.learning_context_snapshot() -> ScopedContextSnapshot`.
- Existing `learning_current_scoped()`, `learning_facet_catalog()` and registration semantics remain compatible. Extract its current synchronous scoped SQL into a shared private reader helper rather than duplicate or weaken it.

- [x] **Step 1 — Write failing real-DB tests.** Reuse `tests/learning/conftest.py`'s `learning` fixture and existing canonical source/admission helpers. Assert the facade equals current canonical entries, captures suppression epochs, excludes forged prefixes/private/local-only/time-sensitive/wrong-authority rows, preserves registered TEXT corrections and forgotten membership, accepts 32 entries and fails on 33. Add `test_snapshot_is_coherent_across_writer_commit` using a WAL temporary DB and a thread barrier after the records SELECT: writer changes an assertion plus suppression in one transaction; returned snapshot must be wholly before or wholly after, never mixed.
- [x] **Step 2 — Observe RED.** Run `PY -m pytest tests/learning/test_context_query_snapshot.py -q`; expect missing snapshot interface failures.
- [x] **Step 3 — Implement the snapshot.** One reader-worker callback and a read savepoint surround shared scoped read plus suppression SELECT. Release the savepoint on success and roll back/release on failure, leaving no open transaction. No writes/migrations, private-worker access from voice or new eligibility SQL. Reader overflow remains ValueError locally, later mapped to unavailable.
- [x] **Step 4 — Observe GREEN/regression.** Run `PY -m pytest tests/learning/test_context_query_snapshot.py tests/learning/test_review_regressions.py tests/test_memory_query.py tests/test_memory_retrieval.py -q`; all must pass. The WAL barrier test must prove an actual writer commit occurred and workers close cleanly.
- [x] **Step 5 — Commit** as `feat(context): expose coherent canonical scoped snapshots` and ledger evidence.

### Task 3: Deterministic selection and bounded evidence

**Files:** Modify `src/jarvis/memory/personal_context_projection.py`; create `tests/learning/test_context_projection.py`.

**Interfaces:**
- Consumes Task 1 requests and Task 2 `ScopedContextSnapshot`.
- Produces frozen `ContextProjection(status: str, reason: str | None, facts: tuple[dict[str, object], ...], selected: tuple[SemanticAssertionRecord, ...], scope_keys: tuple[str, ...], signature: str)`; records/signature stay local. Return fresh provider dictionaries rather than mutable shared internal objects.
- Produces `project_personal_context(snapshot: ScopedContextSnapshot, requests: tuple[PersonalContextRequest, ...]) -> ContextProjection` and `context_scope_signature(snapshot: ScopedContextSnapshot, scope_keys: tuple[str, ...]) -> str`.
- Success fact fields exactly: evidence_ref (turn-local ordinal), scope_key, text, recorded_at (UTC ISO system_from), freshness=`last_known`, optional state from the current typed enum `owned/not_owned/active/completed`. Legacy/TEXT omits state. No source IDs, UUIDs, raw/historical values or inferred dates.

- [x] **Step 1 — Write failing projection tests.** Build fictional records with the existing assertion types and local test builders. Start with `test_vehicle_scope_selects_two_vehicles_among_seven_mixed_items`: two vehicles and five devices, shuffled predicate/UUID order; assert two vehicle facts and no device text. Also assert old predicate-only catalog strings expose no vehicle/device label, without claiming an actual-model failure.
- [x] **Step 2 — Add exact-selection/budget assertions to the failing suite.** Named labels, NFKC/casefold/space matching after grounding, duplicate normalized labels, missing named labels, legacy plural/TEXT with uncertain identity, two scopes with one missing component, deduplication, not_owned/completed, invalid typed metadata and hostile instruction text. Require zero facts for ambiguity, unsupported target, over-four union and budget overflow. Construct serialized array sizes exactly 1,800 and 1,801 bytes with metadata/multibyte text; only 1,800 is selected. Recorded time must equal system_from, not source observed_at or invented event time.
- [x] **Step 3 — Observe RED.** Run `PY -m pytest tests/learning/test_context_projection.py -q`; expect missing projection/signature behavior.
- [x] **Step 4 — Implement deterministic projection.** Scope filters first; all-or-nothing requested union; no top-k or clipping. Exact typed label identity only. Unknown current labels prevent a confident negative target result. Sort output deterministically by scope/predicate/assertion ID; assign ordinal evidence refs. Serialize the complete facts array with compact UTF-8 JSON and no NaN. Fixed statuses/reasons reveal no rejected owner values. Signature is a local SHA-256 of canonical serialized requested-scope records (including value/text, source/version/eligibility metadata) plus those scopes' suppression epochs/state; unrelated scopes are excluded.
- [x] **Step 5 — Observe GREEN.** Run `PY -m pytest tests/learning/test_context_query_contracts.py tests/learning/test_context_query_snapshot.py tests/learning/test_context_projection.py -q`; require all passing, including Review Focus 2 and order permutations.
- [x] **Step 6 — Commit** as `feat(context): project relevant current evidence within fixed budgets` and ledger evidence.

### Task 4: Question-authorized orchestration and one release ledger

**Files:** Modify `src/jarvis/voice/personal_context.py`; create `tests/learning/test_context_query_session.py`; modify `tests/test_personal_context_runtime.py` only where new regressions belong.

**Interfaces:**
- Consumes Task 1 parser, Task 2 retrieval facade and Task 3 projection.
- Produces `PersonalContextSession.query_for_question(self, requests: object) -> dict[str, object]` and read-only property `supports_question_query -> bool` (true when constructed with the learning authority; current grant validity is checked on every execution).
- Session owns one asyncio lock for read/projection state, `_release_path` (`None/legacy/query`), per-turn attempt count and frozen successful request/projection. Legacy read serialization uses private unlocked helpers; never recursively reacquire the lock. Catalog retains its current busy/overlapping-Hello denial behavior.

- [x] **Step 1 — Write failing session tests.** Real temporary canonical DB plus real learning authority fixtures. Assert one owner Hello across fresh wakes, current-question-only source registration, three no-match/invalid attempts then invalid_selection without a fourth DB evaluation, successful identical replay, different query rejection and exception-to-unavailable redaction. Missing learning composition must deny without initiating exact-consent Hello or reopening a session.
- [x] **Step 2 — Add race and legacy tests.** Use asyncio barriers to race new/legacy calls and two different new requests: one winning release, no combined facts/metadata; cross-path calls invalid_selection even for the same facts. Legacy-only repeated behavior remains accepted. Capture fixed logs/provider packets and assert fictional private/withheld canaries and target quotes never appear in diagnostics. Test read permit replaced by mutation while a query awaits storage: the old query cannot release.
- [x] **Step 3 — Observe RED.** Run `PY -m pytest tests/learning/test_context_query_session.py -q`; expect missing query/ledger behavior.
- [x] **Step 4 — Implement orchestration.** Serialize attempts and first release; use `_authorize('read')`, not new authority. Pin the exact permit object, binding and read operation for the query, validate before/after awaits, map failures in spec order, then freeze projection and `_released` together before `_protect()`. Invalid inputs consume a pre-release attempt; no-match/clarification returns zero facts. Replay revalidates without new scope search/release. Legacy successful reads set/check the same release path. No provider text, exception body, query values or raw input in logs.
- [x] **Step 5 — Observe GREEN/regression.** Run `PY -m pytest tests/learning/test_context_query_session.py tests/learning/test_context.py tests/test_personal_context_runtime.py tests/test_memory_tools.py -q`; require all passing. Busy/denial, exact mutation and legacy response contracts must remain intact.
- [x] **Step 6 — Commit** as `feat(context): govern question queries with one answer release ledger` and ledger evidence.

### Task 5: Scope-change invalidation through the actual audio guards

**Files:** Modify `src/jarvis/voice/personal_context.py`; create `tests/learning/test_context_query_lifecycle.py`. Use existing `src/jarvis/voice/personal_context_audio.py` unchanged unless a reproduced guard integration defect requires a focused repair.

**Interfaces:**
- Consumes Task 3 signature and Task 4 query state.
- Extend the existing `_facts_current() -> bool` to revalidate new-query requested-scope signatures as well as exact released versions; legacy validation remains compatible.
- `allow_audio()`, watchdog, close, mutation_committed and mutation_failed remain the lifecycle owners; no new timer/authority/cache owner.

- [x] **Step 1 — Write failing lifecycle tests.** After a unique target release, add/change a previously unselected record to create a second matching label. Assert `allow_audio()` false, queued output cleared and retirement triggered even though the selected assertion ID is unchanged. Repeat for requested-scope suppression epoch, source authority/sensitivity changes, correction/forget and reader overflow. Unrelated-scope changes must keep a still-valid projection usable, except global reader overflow which remains unavailable.
- [x] **Step 2 — Add actual guard-chain and cancellation tests.** Reuse `PersonalContextAudioOutput`/LiveKit AudioFrame fake-sink pattern from `tests/test_personal_context_runtime.py`; assert no frame reaches the sink after invalidation. Test new turn, activity/generation change, expiry, lock/unlock epoch, disconnect, cancellation during snapshot, mutation success/failure and response/playback retirement. Assert no leaked lock, source lease or response surviving close, and no subsequent implicit session renewal.
- [x] **Step 3 — Observe RED.** Run `PY -m pytest tests/learning/test_context_query_lifecycle.py -q`; expect current lifecycle to miss the new scope-signature invalidation case.
- [x] **Step 4 — Implement guard integration.** Compare a fresh coherent snapshot signature at existing validation points; failure closes/clears audio via existing lifecycle. Validate current-question permit before/after storage work and before data/audio release. Reset query state through existing mutation/close paths, without enabling another read permit. Reuse the existing watchdog cadence rather than add inference or polling services.
- [x] **Step 5 — Observe GREEN/regression.** Run `PY -m pytest tests/learning/test_context_query_lifecycle.py tests/learning/test_context_query_session.py tests/test_personal_context_runtime.py tests/test_personal_context_production.py tests/learning/test_authority.py tests/learning/test_forgetting.py -q`; require all passing. This is synthetic chain verification, not manual owner lock/microphone acceptance.
- [x] **Step 6 — Commit** as `fix(context): invalidate projected evidence before personal audio release` and ledger evidence.

### Task 6: Normal voice tool schema, composition and grounded instructions

**Files:** Modify `src/jarvis/voice/personal_context.py`, `src/jarvis/voice/agent.py`; modify `tests/learning/test_production.py`, `tests/test_voice_agent.py`; create `tests/learning/test_context_query_production.py`.

**Interfaces:**
- Produces `PersonalContextAgentTools.read_personal_context_for_question(self, raw_arguments: dict[str, object]) -> dict`, using the pinned LiveKit `function_tool(raw_schema=...)` form. Its provider-visible schema remains exactly `{requests: [PersonalContextRequest]}`; the raw handler validates the closed top-level envelope and delegates the requests to `session.query_for_question`. An invalid envelope delegates an invalid sentinel so the session counts the attempt. Build the explicit schema from the registered enum/contract; never let default SDK Pydantic coercion/null substitution bypass local parsing or echo validation input.
- `PersonalContextAgentTools.tools` retains old tools and includes the new one only when `session.supports_question_query` is true. Existing canonical runtime creates the session with the appropriate mode; do not add a second mode flag to tool construction.
- Agent chooses query instructions only when learning mode is APPLY and the actual new tool ID is present. Learning APPLY missing the new tool retains honest available-tool instructions; it must not name the missing tool. Context-only/OFF retain existing instructions and explicit correction/forget routing.

- [x] **Step 1 — Write failing composition/schema tests.** Assert tool ID presence only in learning composition; inspect the pinned LiveKit function schema for closed scope enum, object fields and bounded request handling. Execute through `livekit.agents.llm.utils.prepare_function_arguments(fnc=tool, json_arguments=payload)` and the registered raw wrapper, not only direct session calls. Valid JSON containing extra root fields, explicit null, invalid scope or wrong request types must reach local validation, consume an attempt and return a fixed invalid_selection without echoed input; unparseable/non-object transport arguments must never reach the handler or read the DB. SDK-repaired object arguments undergo the same strict local checks. Transport parse failures rejected before execution are not query evaluations; this slice does not replace the SDK transport parser. Test configured console/JSONL diagnostics for canary leakage on locally handled invalid requests as well as the returned tool packet; report any upstream SDK diagnostic exposure separately rather than silently broadening the feature. Off/context-only combinations must not advertise the new tool; expired APPLY execution denies and never renews Hello.
- [x] **Step 2 — Add normal-path tests for all three languages.** Extend existing canonical controller/fake LiveKit event/audio harness with seven fictional mixed items. Emit accepted user question, call actual query tool through agent.tools, observe projected facts through guarded output and private response retirement. Assert instructions route ordinary personal advice to the new tool; general/third-party/hypothetical queries require no owner lookup; explicit correction/forget still uses catalog; unknown motives remain unknown; no per-fact save prompt. Label these forced tool/answer harness checks, not proof of real model selection or spoken usefulness.
- [x] **Step 3 — Observe RED.** Run `PY -m pytest tests/learning/test_context_query_production.py tests/test_voice_agent.py -q`; require an absent new schema/instruction/composition failure.
- [x] **Step 4 — Implement wrapper and instruction integration.** Existing realtime model remains the reasoner; evidence is inert and cannot authorize writes/actions. Include last-known/not_owned/completed semantics and truthful no-match/clarification/unavailable responses. Do not broaden retention, alter CLI defaults, add an HTTP planner or silently fall back to fuzzy target matching. Verify the actual pinned raw-schema conversion for Gemini and LiveKit argument binding. Keep external schema and strict local parser in agreement; do not switch back to a coercing typed wrapper. The raw wrapper is an implementation detail preserving the approved provider-visible tool contract, not a new public query shape.
- [x] **Step 5 — Observe GREEN/regression.** Run `PY -m pytest tests/learning/test_context_query_production.py tests/learning/test_production.py tests/test_voice_agent.py tests/test_personal_context_production.py tests/test_context_sync.py -q`; all must pass, with actual tool-set and prompt assertions for each composition.
- [x] **Step 6 — Commit** as `feat(voice): use question-bound personal evidence in normal learning sessions` and ledger evidence.

### Task 7: Whole-candidate verification, latency evidence and honest handoff

**Files:** Create `docs/research/PI3_CONTEXT_QUERY_IMPLEMENTATION_2026-10-22.md`; update `docs/CURRENT_PLAN.md`, `docs/CURRENT_ARCHITECTURE.md`, `docs/PROJECT_STATE.md`, `docs/PRODUCT.md`, `docs/ROADMAP.md`, `docs/PERSONAL_INTELLIGENCE_ENABLEMENT.md`, `docs/README.md` and top-level `README.md` only where current capability/status guidance changes. Create `tests/learning/test_context_query_performance.py` for a bounded local measurement harness.

**Interfaces:** Consumes Tasks 1-6 and existing quality/promotion gates. Produces a reviewed source candidate, reproducible local evidence and a whole-app acceptance protocol; it does not produce a completed live qualification claim without observations.

- [x] **Step 1 — Measure the actual local path.** Parametrize temporary canonical 1/8/32-entry stores (one named vehicle plus unrelated devices as size grows, so the selected result stays within four facts), five warmups and 30 measured catalog/read baseline versus query/projection/guard iterations on fresh bound sessions. Stub only external/native owner verification, never the canonical DB/projection. Use `perf_counter`, record p50/p95/max and a concurrent event-loop heartbeat's maximum delay; no provider calls. Assertions require correct evidence and usable guards, not machine-dependent millisecond thresholds. Save raw timing summary/environment/sample count in the execution workspace; report regressions rather than rerun selectively to improve a score. Run `PY -m pytest tests/learning/test_context_query_performance.py -q -s`; require correct results and captured timing evidence. This is a measurement task, not a new product behavior requiring an artificial RED case.
- [x] **Step 2 — Run final software checks once.** `PY -m pytest -q`, `PY -m ruff check .`, `PY -m ruff format --check .`, and `git diff --check` must pass on the candidate. Use this plan's isolated `JARVIS_MACHINE_CONFIG` fixture path as in Windows CI, restoring any prior environment value afterward. Redirect long output to this plan's workspace, inspect completion/exit code/counts. Explain skips/platform limits. Follow existing Linux, Windows-full, Hello, DPAPI and relevant SQLCipher required checks on the review candidate; never replace them with local synthetic claims or claim old-head CI as current-head evidence.
- [x] **Step 3 — Reconcile status docs and acceptance protocol.** Report approved design/plan, exact candidate/base, changed behavior, RED/GREEN results, latency data, known exact-label/32-record/budget boundaries, dependency on PI-2 and disable/rollback. Preserve PI-2 provider deferrals and default-OFF history. In CURRENT_ARCHITECTURE, label unmerged implementation as a candidate rather than accepted running architecture. Prepare complete-app steps with `--personal-learning apply`, fictional mixed entities/preferences/goals, English/Hindi/Hinglish ordinary questions, ambiguity, unrelated query, unknown reason, corrected/forgotten facts, restart and relevant OFF checks. No standalone microphone demo or requirement for owner-authored scenarios. Mark actual model selection/spoken acceptance PENDING until observed.
- [x] **Step 4 — Complete Native whole-branch review.** Follow executing-plans' one fresh final reviewer and review/fix rules, scoped from `22e4ec7e` plus the approved planning commit through the implementation head; supply spec, plan, diffs, tests and the five Review Focus cases. This is the skill-authorized final review, not delegation of implementation. Security/important fixes require observed RED/GREEN and affected suite verification. Preserve rulings in the plan-specific ledger and summarize outcomes durably before any skill-directed scratch cleanup; do not touch the older PI-2 ledger.
- [x] **Step 5 — Commit/handoff.** Commit reconciled evidence as `docs: record PI3 context query software verification and acceptance limits`. Prepare an isolated review PR against the actual dependency base when appropriate and attach any created PR to this chat. Do not push onto the older shared PI-2 branch or merge/provision/activate under this plan. Report software completion distinctly from remaining CI/provider/normal-app acceptance; request only the concrete next external dependency if needed.

## Execution preparation after plan approval

Use `superpowers:executing-plans` with its own plan-specific workspace/ledger, then load TDD before Task 1 and verify the non-main clean baseline in this same checkout. Preserve prior Native rulings/evidence rather than restarting old PI-2 work. Review all Interfaces for shared contracts before editing; decide routine ambiguities against the approved spec, record each ruling and continue without between-task permission prompts. Observe failing tests before product changes; do not repeat an implementation already committed after compaction.

## Plan self-review / coverage

- Spec sections 1-3 (goal, fit, permission/mode) map to Tasks 4/6/7; no new engine, data scope or per-fact confirmation is introduced.
- Spec sections 4-5 (requests, canonical selection, statuses/evidence/budgets) map to Tasks 1-4; exact seven keys, 256 bytes, three attempts, 32 assertions, four facts and 1,800 bytes are pinned.
- Spec section 6 (shared release/currentness/audio) maps to Tasks 2/4/5, including atomic read, concurrency, scope membership, source/suppression and lifecycle reset.
- Spec section 7 (normal-model composition/limits) maps to Task 6 plus Task 7's separately pending actual-model acceptance.
- Spec sections 8-9 (verification, dependencies, rollback/promotion) map to Task 7 and the global constraints; no deferred result is marked passed.
- Interfaces use the same request/snapshot/projection/session names throughout. Each of the five Review Focus inputs has a named task test. Product behavior tasks carry RED/GREEN/commit steps; measurement/docs/review use direct evidence instead of implementation-mirroring tests. This is author self-review, not owner plan approval or completed implementation review.
