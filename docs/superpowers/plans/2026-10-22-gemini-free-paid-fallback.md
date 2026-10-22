# Gemini Free-first / Paid-fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native execution is already selected; do not ask for the method again. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, cost-governed Gemini Free/Paid invocation and safe Live continuity through existing routing owners.

**Architecture:** Extend Global Brain Router / Phase-4 ModelRouter, target adapters, health, persistence and cost accounting. Reuse canonical conversation, tools/Authority and private-memory state across transport replacement. Paid invocation stays disabled until explicitly activated and priced; implementation verification uses fake clients.

**Tech Stack:** Existing Python3.11, dataclasses/Pydantic, SQLiteWorkStore extension transactions, asyncio, google-genai2.22.0 and LiveKit Agents/Google plugin1.8.3; no new dependencies.

**Spec:** [Owner-approved written design](../specs/2026-10-22-gemini-free-paid-fallback-design.md), approved as “Approve written design” on22 October2026.

**Status:** OWNER-APPROVED plan: “Approve plan — continue Native implementation.” Implementation in progress. Baseline design commit `94802e07`, atop PI-3A `211c3ade` and unmerged PI-2/PI-3A dependencies. Preserve existing Desktop checkout; use an isolated non-main feature branch after plan approval. No product implementation, paid request, activation or billing operation has occurred.

## Global Constraints

- `GOOGLE_API_KEY` remains Free; Paid is `JARVIS_GEMINI_PAID_API_KEY`; dedicated TTS stays independent. Allowlisted environment references only; no keys in logs/reprs/persistence or global environment switching.
- Preserve deterministic/cached/local and configured ChatGPT-plan priority; no competing router or account/project rotation. New Paid edge is quota/rate-limit-only, not503/auth/configuration errors.
- `JARVIS_GEMINI_PAID_FALLBACK_ENABLED` defaults false. Existing machine-setting precedence applies. No live inference/probes, owner-app activation, billing/purchases or protected merge during implementation.
- Initial ceiling INR350/35000paise, cumulative for an explicit budget identity; no automatic restart/day/month reset/top-up. Unknown costs stay unknown/reserved, never zero.
- Pin reviewed model/service/modality price version/effective times and FX source/version/margin; missing/stale/unsupported rates, usage or request bounds exclude Paid. No invented production rates or FX defaults.
- Preserve existing serialized inputs/digests while disabled and replay v1 decisions against original registry. New scope/registry/budget records are additive within ModelRoutingStore/SQLiteWorkStore.
- At most one Paid visit per request: Free->Paid two target visits, configured ChatGPT-plan->Free->Paid three. No hidden SDK retry multiplication. Existing unrelated resilience/local fallback stays governed.
- Demand recovery uses one durable half-open claim; unknown429 cooldown60s doubles to900s. Trusted daily reset uses America/Los_Angeles/DST. Never interrupt input/output speech or tools to recover Free.
- Preserve accepted canonical context/tools across safe Live failover without another wake where possible; never replay raw/unaccepted audio, already heard replies or mutating actions; no cross-project resumption handle.
- Preserve private-grant maximum900s/idle300s, release budget/currentness/suppression, source identity, one-shot Authority, TTS, context-only/OFF and history retirement.
- Observed RED/GREEN before product code; one final fresh review, one repair pass if required, final full suite/lint/format/whitespace and exact-head hosted checks. Provider/owner acceptance stays pending until observed.

## Review Focus

1. Crash after Paid dispatch before settlement retains uncertain exposure and cannot duplicate spending/action (Tasks3/6/11).
2. Daily reset/Retry-After and multiprocess Free recovery yield one real half-open request without health generations (Task4).
3. Late old Live events/internal SDK reconnect cannot close canonical history, leak context, learn twice or replay tools (Tasks8/9/11).
4. Config/price/credential additions cannot change legacy registry digests or strand durable v1 Work (Tasks1/2/6).
5. Partial/cumulative/modality usage cannot hide thought/audio/context cost or bypass the35000paise ceiling (Tasks3/9/11).

## File responsibility map

Existing `ai_provider.py`/`config.py` own credentials/config. Existing `model_routing/{models,registry,router,eligibility,store,strategy,health,invoker,cost}.py` retain routing/cost authority; new focused `model_routing/{gemini,pricing,budget,runtime}.py` are subordinate helpers/composition, not new routers/databases. Existing `brain_routing/work.py`, `work/{reasoner,runtime}.py` retain Work identity/execution. Existing Hands/memory adapters consume shared inference. Existing voice bridge/resilience/controller/factories own handoff; new `voice/{gemini_handoff,gemini_budget}.py` implement fencing/accounting, never independent selection. New tests live under `tests/gemini_fallback/`; current regression suites remain authoritative. Dated report/current docs preserve actual evidence.

### Task 1: Credential-aware targets and opt-in configuration

**Files:** Modify `src/jarvis/ai_provider.py`, `config.py`, `model_routing/models.py`, `model_routing/router.py`; create `model_routing/gemini.py`, `tests/gemini_fallback/{conftest,test_credentials,test_targets}.py`.

**Interfaces:** Add `gemini_credential_ref(slot: Literal['free','paid']) -> str`, `resolve_target_api_key(target: ModelTarget) -> str` with allowlisted refs. `GeminiFallbackConfig(enabled=False, budget_id='gemini-paid-fallback-v1', ceiling_inr_minor=35000, cooldown_seconds=60, max_cooldown_seconds=900, pricing_path: Path|None=None)` validates strict finite/positive values. `build_gemini_role_targets(*, role, model, adapter_id, config, cost_profile=None) -> tuple[ModelTarget,...]` produces role/model/slot targets; disabled legacy builders/digests stay exact.

- [x] **Step1 — Failing tests:** `test_independent_keys`, `test_tts_not_paid_fallback`, `test_missing_paid_key_never_uses_free_as_paid`, `test_secrets_absent_from_diagnostics`, `test_disabled_legacy_digest`, config precedence/invalid cap. Use canaries and block external network in this test package.
- [x] **Step2 — RED:** `PY -m pytest tests/gemini_fallback/test_credentials.py tests/gemini_fallback/test_targets.py -q`; expect absent contracts/behavior, not fixture errors.
- [x] **Step3 — Implement interfaces/config:** preserve provider/TTS defaults; no key reads on import, environment rewriting or implicit activation. Missing Paid key/config excludes Paid.
- [x] **Step4 — GREEN:** same tests plus `tests/test_c2_tts_separation.py`, `tests/test_ai_provider_policy.py`, `tests/test_config.py`, `tests/test_provider_cli.py`, `tests/test_model_routing_models.py`, `tests/test_model_routing_registry.py`, `tests/test_model_routing_strategy.py`.
- [x] **Step5 — Commit:** `feat(routing): add independent Gemini credential targets`; ledger actual evidence.

### Task 2: Scoped requests in the same router/store and immutable replay

**Files:** Modify `model_routing/{models,eligibility,registry,router,store}.py`; tests `tests/gemini_fallback/{test_scoped_routing,test_replay_compatibility}.py`.

**Interfaces:** `ScopedRoutingRequest` has routing_request_id, scope_kind(voice/hands/memory), scope_id and existing non-Work eligibility/strategy facts: task_kind, strategy_key/version, required_capabilities, privacy_class, locality_requirement, estimated_context_tokens, evidence_size_class, recent_progress/failure_signals, latency_preference, cost_preference, routing_features. No work_id/fake WorkItem. Extend `ModelRouter.route(request: RoutingRequest|ScopedRoutingRequest) -> RoutedSelection` and EligibilityPolicy through the same selection algorithm. Store adds `record_scoped_decision`, `find_scoped_decision_by_request`, `record_scoped_attempt` plus immutable registry snapshots; old Work methods/tables remain intact. `ModelTargetRegistry.to_snapshot()`/source-allowlisted `from_snapshot(...)` and replay resolve recorded digest/policy, not current config. RoutedSelection.request accepts the union.

- [ ] **Step1 — Failing tests:** scope decisions/health/eligibility create no WorkItem; old payload golden fixtures/digest remain exact; v2 reloads original targets after config changes; tampered/unrecoverable snapshot fails closed; v1 replay remains valid while new requests enable fallback.
- [ ] **Step2 — RED:** run scoped/replay tests; require unsupported request/persistence failures.
- [ ] **Step3 — Implement additive scope/registry tables** with extension_transaction/encoded payloads; preserve old digest shape when additions absent. Validate scope/request/decision identity transactionally; factor shared selection/persistence dispatch, no second policy class.
- [ ] **Step4 — GREEN:** new tests plus `test_model_routing_store.py`, `test_model_routing_eligibility.py`, `test_model_routing_status.py`, `test_global_brain_router.py`.
- [ ] **Step5 — Commit:** `feat(routing): persist scoped inference with legacy replay compatibility`.

### Task 3: Versioned prices, shared atomic reservations and unknown costs

**Files:** Create `model_routing/{pricing,budget}.py`; extend `cost.py`, `store.py`, `models.py`; tests `tests/gemini_fallback/{test_pricing,test_paid_budget,test_budget_concurrency}.py`.

**Interfaces:** `PricingSnapshot` pins model/service/modality, profile ID/version/effective times and FX source/version/effective times/margin. `load_pricing_snapshot(path: Path, *, now_epoch: float) -> PricingSnapshot`. `PaidExposure` describes bounded context/input/output/thinking/modalities/duration. `PaidBudgetGovernor(store: ModelRoutingStore, *, config, clock)` provides `reserve(*, invocation_id, target, exposure, pricing) -> PaidReservation`, `mark_dispatched(reservation_id)`, `settle(*, reservation_id, usage, usage_complete, event_id)`, `cancel_unsent(reservation_id)`, `status(budget_id)`. Extend existing cost readers to lane/target/known/reserved/unknown/version facts; old unknown cost stays None. PaidReservation contains reservation_id, budget_id, invocation_id, target_id, price_profile_id/version, reserved_inr_minor and dispatch/settlement state; status reports ceiling/spent/reserved/unknown separately. Store integer-paise ledgers in the same database without private payloads.

- [ ] **Step1 — Failing tests:** default35000/restart; exact boundary; multi-connection/process races; duplicate invocation/event idempotence; dispatched timeout/cancel/crash retains exposure; only proved-unsent refunds; missing/stale/negative/NaN/partial rate/FX rejects Paid; unknown usage never zero. Fixtures use synthetic prices, not production claims.
- [ ] **Step2 — RED:** run price/budget suites; require missing enforcement.
- [ ] **Step3 — Implement Decimal/conservative rounding and transactional reservations.** Pin effective profiles, retain uncertainty after restart/lease expiry, record overrun/block further admission rather than clip actual cost. Add modality prices without altering legacy absent-field serialization/digests.
- [ ] **Step4 — GREEN:** new tests, `tests/test_cost_telemetry.py` and model-routing model/store regressions; real SQLite multiprocess races, not just asyncio locks.
- [ ] **Step5 — Commit:** `feat(cost): enforce restart-safe paid fallback reservations`.

### Task 4: Quota-only edge, credential failures and demand recovery

**Files:** Modify `provider_resilience.py`, `model_routing/{health,gemini,store}.py`; tests `tests/gemini_fallback/{test_pressure_policy,test_free_recovery}.py`.

**Interfaces:** Add typed depleted-balance402 recognition without changing old enum values. `gemini_paid_fallback_allowed(failure: ProviderFailure, *, source_target: ModelTarget) -> bool` only permits Free pressure. `claim_free_recovery(*, target_id, operation_id, now_epoch, lease_seconds) -> RecoveryLease|None`, with immutable RecoveryLease(target_id, operation_id, expires_at_epoch, version); release/complete require the matching lease version and live in existing health/store. `record_pressure` accepts trusted sanitized Retry-After/reset facts; config60/900 bounds; unrelated health behavior unchanged.

- [ ] **Step1 — Failing tests:** typed429/Live quota allows edge;401/403/400/404/402/503/timeout/unknown cannot create paid hop. Paid402 disables its credential scope, not Free/TTS. Model429 stays local. One multiprocess recovery claim, no probe before demand. Pacific DST daily reset; ambiguous RESOURCE_EXHAUSTED uses cooldown, not guessed daily reset.
- [ ] **Step2 — RED:** run pressure/recovery tests; require missing policy/leases.
- [ ] **Step3 — Implement classification precedence** so401/403 cannot be overridden by stray quota text. Persist health/half-open claims; no secret/raw payload logs or cross-caller lease corruption.
- [ ] **Step4 — GREEN:** new tests plus `test_provider_resilience.py`, `test_model_routing_health.py`, `test_model_routing_fallback.py`, `test_model_routing_provider_retry_boundary.py`.
- [ ] **Step5 — Commit:** `feat(resilience): add quota-only Gemini fallback and demand recovery`.

### Task 5: Shared target-aware invocation and paid admission

**Files:** Modify `model_routing/{invoker,router,gemini,cost}.py`, `hands/provider_adapters.py`; tests `tests/gemini_fallback/{test_invocation,test_retry_boundaries}.py`.

**Interfaces:** Extend `build_structured_output_client(..., credential_ref: str|None=None)` compatibly; StructuredOutputModelAdapter caches by target slot/model/generation and forwards credential_ref. Add scoped invocation context alongside existing ModelInvocationContext without changing Work constructor behavior. Extend `ModelInvoker(registry, *, paid_budget: PaidBudgetGovernor|None=None, pricing: PricingSnapshot|None=None)` with reserve-before-dispatch/settle hooks. Add `invoke_scoped_structured(*, router: ModelRouter, request: ScopedRoutingRequest, system_prompt: str, input_payload: dict, response_model: type[BaseModel], exposure: PaidExposure) -> StructuredOutputTelemetry`; it delegates all selection to that router/shared pressure policy. Stable operation IDs, privacy/exposure facts are required; inference never executes capabilities.

- [ ] **Step1 — Failing tests:** Free success only Free; Free429->Paid once with correct key/reservation; exhausted/unavailable/auth-failed Paid terminates; max2 Free/Paid visits and max3 including configured ChatGPT-plan. No invisible SDK retries. Failed Free and Paid target/correlation/usage facts persisted. Missing price/output bound means no Paid request.
- [ ] **Step2 — RED:** run invocation/retry tests; require missing credential/admission behavior.
- [ ] **Step3 — Implement through existing router/invoker.** Evolve client factory by an explicit compatible adapter, not catching arbitrary TypeError and constructing twice. Paid output bounds are required/sent via pinned SDK config; disabled/Free defaults unchanged. No hidden SDK retries on router-owned requests. Legacy direct Work invocation also enforces budget whenever its selected target is Paid.
- [ ] **Step4 — GREEN:** new suites and existing structured-provider/invoker/routing regressions identified in pre-flight. Canary credentials absent from exceptions/logs/persisted records.
- [ ] **Step5 — Commit:** `feat(inference): share bounded Gemini credential-target invocation`.

### Task 6: Durable Work wiring without replaying execution

**Files:** Modify `work/{reasoner,runtime}.py`, `brain_routing/work.py`, `model_routing/router.py`; create `model_routing/runtime.py`; tests `tests/gemini_fallback/{test_work_resume,test_work_priority}.py`.

**Interfaces:** `RoutingRuntime` is a composition holder for existing router/store/invoker/budget/health, not another router. `build_routing_runtime(*, work_store: SQLiteWorkStore, provider, model, config: GeminiFallbackConfig, chatgpt_plan_session=None) -> RoutingRuntime`. Extend `build_work_runtime(..., routing_runtime: RoutingRuntime|None=None)` compatibly; production injects shared services. Keep GlobalBrainRouterReasoner/RoutedWorkReasoner. v1 requests retain original registry/policy; new opt-in decisions pin v2 graph/prices once.

- [ ] **Step1 — Failing tests:** deterministic/ChatGPT-plan still wins. v2 Free429->Paid persists lineage, restarts same WorkItem and does not duplicate request/attempt/reservation/action. Crash after dispatch before result stays uncertain/blocked rather than reissued. v1 replay works and never silently acquires Paid edge.
- [ ] **Step2 — RED:** run Work suites; require missing wiring/compatibility behavior.
- [ ] **Step3 — Inject shared services; preserve execution ownership.** Keep WorkStep actions/checkpoints/Authority permits. Change inference/attempt/health/cost only. Preserve existing OpenAI/local configuration and privacy. Reuse approved historical pools/snapshots rather than resetting lineage on current-registry mismatch.
- [ ] **Step4 — GREEN:** new Work suites, global-brain, model-routing acceptance/fallback/status/store and existing Work recovery tests; no real Google/DBOS calls in synthetic fixtures.
- [ ] **Step5 — Commit:** `feat(work): preserve durable lineage through Gemini fallback`.

### Task 7: Hands and memory inference integration

**Files:** Modify `hands/provider_adapters.py`, `memory/{learning_extractors,runtime}.py` , `memory/extractors.py` and `memory/query_interpreters.py`; tests `tests/gemini_fallback/{test_hands_memory,test_memory_authority}.py`.

**Interfaces:** Optional RoutingRuntime injection and stable lane/source/operation IDs at existing adapter construction; no new planner. LearningProviderAdapter keeps sanitized public errors while retaining typed ProviderFailure internally. extract/resolve response contracts unchanged. Reuse original structured/source validation, never retry around admit_learning or Hands execution.

- [ ] **Step1 — Failing tests:** Free/429/Paid behavior for Hands planning, extraction, resolution and eligible semantic recall. Hands action counter remains one after success/uncertain action. Source expiry, suppression/forget/currentness/permit change or deadline during fallback blocks memory admission/release. Dedicated TTS, ChatGPT-plan and local-only exclusion unchanged.
- [ ] **Step2 — RED:** run new Hands/memory tests using real temporary canonical memory/service and fake inference; require missing integration.
- [ ] **Step3 — Implement inference-only integration.** Preserve original source deadlines/grants/validators after await; memory4096 output bound stays. Paid Hands requires reviewed output bound without changing disabled/Free behavior. No private prompts in routing/cost diagnostics; no write-admission retries.
- [ ] **Step4 — GREEN:** new suites plus Hands provider/planner, all `tests/learning`, relevant memory query/retrieval/context/forget regressions; group test paths consistently with fixtures.
- [ ] **Step5 — Commit:** `feat(assistants): integrate governed Gemini fallback in Hands and memory`.

### Task 8: Live handoff with canonical context and tool continuity

**Files:** Create `voice/gemini_handoff.py`; modify `voice/{livekit_session,provider_resilience,runtime,canonical_active_speaker_runtime}.py`; tests `tests/gemini_fallback/{test_live_handoff,test_live_context,test_live_tool_replay}.py`.

**Interfaces:** `GeminiLiveHandoff` belongs to existing resilience/controller and consumes RoutingRuntime, AgentSession/agent, bridge and guard callbacks. Methods `async handle_failure(failure: ProviderFailure) -> bool`, `async maybe_recover_free() -> bool`, `close()`; no target selection independent of ModelRouter. Bridge gains transport epoch/fence and accepted-context projection without observer notifications/final logical close during intentional swap. `_create_realtime_model(config, *, target: ModelTarget|None=None)` resolves explicit target key/options. Use supported Agent.update_options(llm=new_model) with explicit authorized ChatContext restoration, verified against pinned SDK.

- [ ] **Step1 — Failing tests:** actual registered SDK-event/controller harness Free quota replaces model once, keeps canonical session ID/accepted turns/tools and continues a safe unanswered request without new wake. Restored messages are not relearned; completed tools not re-executed. Bounded Paid setup failure; old error/close/audio ignored. Pending mutation/partly heard reply yields safe uncertainty, not full replay. Free handle never passed to Paid.
- [ ] **Step2 — RED:** run Live suites; require current close-on-failure/context/replacement failures.
- [ ] **Step3 — Implement bounded handoff.** Keep logical bridge/observers/audio/tools/options/voice/private state. Validate grants/currentness after awaits and before restore/output. No Hello/900s/300s renewal or retired history resurrection. Fence SDK internal restart as well as public close events. If supported model replacement cannot preserve contracts, report exact blocked case and fail closed rather than mutate untested SDK internals. Task8 alone cannot activate Paid Live before Task9 gates it.
- [ ] **Step4 — GREEN:** new suites plus `tests/test_livekit_session.py`, `tests/test_livekit_context_adapter.py` and existing production/provider-resilience/context/lifecycle regression, fake sockets/providers and real pinned schema/event conversion.
- [ ] **Step5 — Commit:** `feat(voice): preserve canonical state across Gemini target handoff`.

### Task 9: Paid Live streaming budget, modality usage and safe recovery

**Files:** Create `voice/gemini_budget.py`; modify `voice/{gemini_handoff,livekit_session}.py`, `model_routing/{pricing,budget,cost}.py`; tests `tests/gemini_fallback/{test_live_budget,test_live_recovery}.py`.

**Interfaces:** `GeminiLiveBudget` pins target/transport epoch/price snapshot. Methods `async reserve_interval(exposure: PaidExposure)`, synchronous `allow_input(*, modality, quantity, now_epoch) -> bool`, `observe_usage(*, event_id, usage, cumulative, complete)`, `close(*, uncertain: bool)`. Wrap the supported Google model/session boundary to gate audio/video/text before send. Reuse usage metrics and modality metadata with epoch/event deduplication; preserve public model/session protocol.

- [ ] **Step1 — Failing tests:** no Paid frames without reserve; next interval denial at35000 stops forwarding/uses local status. Duplicate/cumulative/partial/thinking/cached/audio/video/context usage cannot double count or become zero. Close/crash retains unknown exposure. Free recovery defers through input/output/tools, then one demand-driven attempt keeps context without health probes. Missing audio price excludes Paid Live.
- [ ] **Step2 — RED:** run Live budget/recovery suites; require missing gating/accounting.
- [ ] **Step3 — Implement bounded interval gates.** Reserve ahead off event loop; frame path consumes only existing proved reserve. Review context/input/output bounds and set supported SDK max_output_tokens. Automatic reconnect/context reprocessing reserves again. No private SDK patch or hard-invoice-cap claim. Incomplete usage stays unknown; no defensible bound means Paid unavailable, not unbounded streaming advertised as protected.
- [ ] **Step4 — GREEN:** new suites plus Tasks3/4/8, existing full-duplex/output guard and private-context source/forget/expiry regressions. Measure gate overhead/heartbeat with fictional data once; no brittle timing assertions/selective score reruns.
- [ ] **Step5 — Commit:** `feat(voice): bound paid streaming and recover Free at safe boundaries`.

### Task 10: Shared production composition, preflight and status

**Files:** Modify `voice/{production_runtime,canonical_active_speaker_runtime}.py`, `work/runtime.py`, `model_routing/runtime.py`, `config.py`, `src/jarvis/preflight.py` and existing model-routing status module; tests `tests/gemini_fallback/{test_production_composition,test_status}.py`.

**Interfaces:** Production builds/injects one RoutingRuntime from existing protected SQLiteWorkStore; Work/Hands/memory/Live share its router/store/governor. Work-disabled voice can initialize routing/cost extension storage without fake WorkItems or DBOS execution. Preflight/status shows effective mode, slot availability, target/cooldown, known/reserved/unknown spend and pricing validity; no key/probe. Disabled construction stays compatible/lazy.

- [ ] **Step1 — Failing tests:** full production factory shares services across lanes; Work-disabled voice does not start DBOS. OFF constructs no Paid clients/network calls and preserves defaults. Missing/wrong price/key/cap yields sanitized status; TTS/ChatGPT/local unchanged. Startup/lifecycle realtime speech cannot bypass budget through an extra model.
- [ ] **Step2 — RED:** run production/status suites; require missing composition/status.
- [ ] **Step3 — Wire existing factories.** No machine-setting edits, key rewriting, normal-app startup or discovery/probe call. Startup greeting, proactive Work delivery and ephemeral Gemini Live messages share eligible credential/budget path; dedicated TTS/local announcements remain independent.
- [ ] **Step4 — GREEN:** new suites plus existing setup/config/provider CLI, startup/standby, Work builder and memory runtime regression tests.
- [ ] **Step5 — Commit:** `feat(runtime): compose shared Free Paid routing and cost status`.

### Task 11: Cross-lane crash/concurrency and duplicate-action verification

**Files:** Create `tests/gemini_fallback/{test_system_boundaries,test_crash_recovery}.py`; product changes only for reproduced failures.

**Interfaces:** Consume Tasks1-10 public production composition, canonical temporary stores, real Authority and fake OS/provider transport with action counters. No simplified test-only routing/governor implementation.

- [ ] **Step1 — Add adversarial tests:** concurrent Paid Live/Work/Hands/memory share35000 ceiling across independent connections/processes; kill after dispatch/settlement; old Live events during lock/forget; v1/v2 Work restart with config change; Paid402 then Free recovery; ChatGPT-plan availability drift; completed/uncertain send/click/write does not execute twice. Canary secrets/private text absent from logs/telemetry.
- [ ] **Step2 — Observe uncovered RED:** run system/crash suites. Already passing cases are additional verification, not fictitious pre-implementation RED. Diagnose failures before minimal fixes; no unrelated refactor.
- [ ] **Step3 — GREEN:** all `tests/gemini_fallback` and learning/routing/global-brain/cost/resilience plus affected voice/Hands/Work suites. No live inference/owner DB access.
- [ ] **Step4 — Commit:** `test(routing): verify cross-lane spend and duplicate-action boundaries`.

### Task 12: Final review, full verification and truthful acceptance handoff

**Files:** Create `docs/research/GEMINI_FREE_PAID_FALLBACK_IMPLEMENTATION_2026-10-22.md`; update `README.md`, `docs/{CURRENT_PLAN,CURRENT_ARCHITECTURE,PROJECT_STATE,PERSONAL_INTELLIGENCE_ENABLEMENT,README}.md` only for this candidate. Preserve historical PI-2/provider deferrals.

**Interfaces:** Produce software-verified isolated dependent candidate, evidence/rulings/limits and exact whole-app acceptance steps. Paid owner-machine acceptance remains separately approved.

- [ ] **Step1 — Record source/compatibility:** changed files/owners, old/new registry identity, credentials/order/bounds, budget persistence/unknowns, measured overhead, disable/rollback, SDK/live limits. Include all Native rulings/costs/deferred minors. Do not claim pricing/account/FX readiness without evidence.
- [ ] **Step2 — Native final review:** one fresh most-capable reviewer with spec/plan/diff/evidence and five Review Focus cases. No implementation delegation/second re-review. One Important/Critical repair pass with observed RED/GREEN; minor findings deferred durably under Native workflow.
- [ ] **Step3 — Final checks:** `PY -m pytest -q`, `PY -m ruff check .`, `PY -m ruff format --check .`, `git diff --check` on final repaired code. Isolate JARVIS_MACHINE_CONFIG in this plan's scratch folder and restore prior env; read real exit/count/skips. Repeat full suite only when changes/failure/review repair justify it.
- [ ] **Step4 — Hosted checks:** isolated draft PR against actual dependency `feat/pi3-question-context-20261022`, never overwrite #295/#296 or merge main; attach created PR. Verify exact-head Linux/Windows/Hello/DPAPI and relevant SQLCipher; dispatch existing SQLCipher workflow if dependent base excludes main-only trigger. Track documentation-only head changes honestly.
- [ ] **Step5 — Owner acceptance:** exact final checkout/update/launch and nonsecret config steps, pricing/FX file example (synthetic until actual reviewed rates populated), persisted INR350 budget and opt-in. Paid test needs explicit request-count/Live-duration/exposure approval first. Whole app, fictional English/Hindi/Hinglish data, acceptance-harness quota/recovery/402 injection, safe no-extra-wake continuation, same WorkItem restart and action count. Do not burn actual quota/balance, edit billing, reset memory or substitute isolated mic tests. Spoken/model/paid acceptance stays pending until observed.
- [ ] **Step6 — Commit/handoff:** save report/evidence/rulings before deleting only this plan's scratch directory. Keep Desktop checkout/branch/older plan folders. Report software separately from activation/provider acceptance/merge; request only the concrete owner-dependent next step.

## Execution preparation

After owner plan review, load executing-plans, TDD, using-git-worktrees and verification skills. Honor existing Desktop checkout preference; verify/create an isolated non-main feature branch from this plan commit. Initialize only `.superpowers/sdd/2026-10-22-gemini-free-paid-fallback/` ledger/briefs; record shared-interface conflicts/rulings against approved spec, then execute without between-task permission prompts. Native is retained. Implementation approval does not authorize paid calls, saved settings, local activation, purchases or merge.

## Plan self-review / coverage

Spec1-3 -> Tasks1/2/5/10; spec4 -> Tasks4/5/9; spec5 -> Tasks3/9/11; spec6 -> Tasks2/6/11; spec7 -> Tasks8/9/11; spec8 -> Tasks5-7/10; spec9 -> Tasks11/12. All five Review Focus cases have owning tests. Shared interfaces (config/targets -> scoped routing/store -> budget/health -> invoker -> Work/Hands/memory/Live -> production) are defined once and consumed by name. No competing router/database, invented price, unknown-as-zero estimate, fake WorkItem or OFF-only acceptance substitutes for the requested behavior. No product implementation has started merely because this plan exists.
