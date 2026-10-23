# Controlled Gemini Paid Live Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native offline execution was explicitly selected by the owner with written-design approval23October2026. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete eligible Gemini Free-to-Paid voice continuity using a public client-owned, pre-admitted Live transport, then return to Free on safe actual demand.

**Architecture:** Keep the existing ModelRouter, RoutingRuntime, PaidBudgetGovernor, GeminiLiveHandoff, canonical bridge and private/Authority owners. A narrow public RealtimeModel/RealtimeSession wraps public Google GenAI Live, with client activity and blocking tools. Paid physical connections close after completed user turns (no idle paid listener); the same logical conversation/tool instances remain alive and subsequent speech receives a new admission and canonical context.

**Tech Stack:** Existing pinned Python3.11, google-genai2.22.0, LiveKit1.8.3 public APIs, existing bundled Silero/local turn control, existing protected SQLite routing/cost stores. No dependency upgrade, SDK-private mutation, account change or inference probe.

**Spec:** `docs/superpowers/specs/2026-10-23-gemini-paid-live-controlled-transport-design.md` (owner approved). Existing Free/Paid design and software checkpointbbaa99d4 remain dependencies, not a fresh router design.

## Global Constraints

- Native offline implementation/review is authorized; real Paid API calls, activation, billing/account changes, purchases and merge are NOT authorized.
- One existing35000paise cumulative, restart-safe shared governor across voice/Work/Hands/memory. Known prices/FX/usage and bounded exposure are mandatory; missing is not zero.
- Free path/model/voice/dedicated TTS/local fallback and existing ChatGPT-plan priorities remain unchanged. New Paid edge is only typed quota/rate pressure.
- Exact installed public interfaces only; no imported private SDK converters, retries/resumption loop, alternate router/authority/personal-memory store or new speaker grant.
- Preserve original canonical session/accepted turns/tools/private source, forget/correction, release limits, expiry and lock boundaries across transport changes.
- Audio PCM16mono16kHz input /24kHz output; deny Paid video. Use public client activity_start/end with automatic server VAD disabled; standard3.8 blocking tools, no extended-thinking alias.
- Client bounded queues; no SQLite/filesystem/provider call in synchronous audio frame forwarding. Reserve/settle off the realtime frame path, revalidate original authority after waits and before any release.
- Full model input/output limits are research inputs, not proof of auxiliary transcription/thinking/listening costs. Task1 must justify every bound or retain explicit denial. Never invent a token/second hard limit.
- Preserve v1/v2 durable replay and current structured candidate; no owner stores or saved machine/environment mutation.

## Review Focus

1. User speaks during setup/output/tool wait or changes/forgets a fact during admission: no unreserved PCM/private release, stale playback or repeated action; Task3/4/5 tests.
2. Setup/history/tool response generates an extra response, GoAway arrives before usage, or an event repeats: prior admission for every trigger, no hidden reconnect/unknown refund; Task1/2/3 tests.
3. Missing/partial/modal/transcription/thinking/cached/cumulative usage, unpriced dimension or a mislabeled model alias: reject/retain exposure, never underprice/mark healthy; Task1/2 tests.
4. Paid socket remains idle, source expires while worker is blocked, cancellation happens after reserve/send, or another process spends the ceiling: no unbounded listener/lifetime, no new grant or concurrent overspend; Task2/3/5 tests.
5. Real pinned AgentSession receives generation/tool/interrupt/end events in unexpected order: preserved canonical conversation, local-VAD pause behavior and safe Free recovery; Task3/4/5 tests.

## File ownership and task interfaces

- Create `voice/gemini_live_contract.py`: strict model/protocol/cost exposure and usage normalization, no transport/router.
- Create `voice/gemini_live_budget.py`: per-connection/generation reservation lifecycle on the existing governor, no provider network.
- Create `voice/gemini_live_model.py`, `voice/gemini_live_session.py`, `voice/gemini_live_events.py`: public LiveKit model/session and public Google protocol/streams; bounded async IO only.
- Modify `voice/gemini_transport.py`, `voice/gemini_handoff.py`, `voice/livekit_session.py`, `voice/production_runtime.py`: original production handoff and public activity delegation, no competing controller.
- Modify `model_routing/status.py`, relevant config only if new explicit bound diagnostics need it; reuse original keys/price catalog and OFF flag.
- Tests under `tests/gemini_live/` reuse existing no-network fixtures, actual AgentSession/Authority/canonical temporary stores and fake public transport. Existing `tests/gemini_fallback` stay regression owners.

### Task 1: Prove and encode the supported model, charging triggers and usage contract

**Files:** Create `voice/gemini_live_contract.py`, `tests/gemini_live/{conftest,test_contract}.py`; record `docs/research/GEMINI_CONTROLLED_LIVE_CONTRACT_2026-10-23.md`.

**Interfaces:** `LiveContractUnavailable(ValueError)`; frozen `LiveModelContract` with model/source/version, full input/output/modal/transcription bounds, maximum activity30s and physical lifetime60s. `reviewed_live_contract(model_id: str, *, auxiliary_bounds: LiveAuxiliaryBounds | None = None) -> LiveModelContract`; `.exposure(scope_id: str) -> PaidExposure`; `normalize_live_usage(raw, *, contract) -> tuple[dict[str,int], bool]`. `LiveAuxiliaryBounds` pins model, three positive auxiliary token bounds, response-text usage mode, source/version. Missing production proof remains denial; synthetic values are software fixtures only. Only qualified exact standard3.8 model accepted. Price dimensions must cover native input/output and separately billed text transcription/thinking; do not infer absent costs are free.

- [x] **Step1 RED tests:** `test_unknown_alias_or_extended_thinking_denied_before_client`; `test_full_context_and_transcription_exposure_is_priced`; `test_partial_or_unpriced_usage_not_zero`; `test_thought_cache_modal_totals_and_repeated_snapshots`; `test_model_limit_alone_does_not_qualify_unknown_auxiliary_bound`. Assert unsupported proof raises before any client construction; no synthetic rate can certify an unknown production model.
- [x] **Step2 Observe RED:** `PY -m pytest -o addopts= tests/gemini_live/test_contract.py -q`. Expected missing contract interface or reproduced unsafe normalization; not fixture/import typos.
- [x] **Step3 Implement:** qualify fields against official Live protocol, standard3.8 model card, thinking and billing docs plus pinned SDK schemas. Explicitly account persistent context, listening and ASR text; derive per-exchange conservative bounds without approximate audio-rate assumptions. Keep unsupported exact config denied if any charge cannot be bounded. Real provider validation remains separate, not assumed from SDK field presence.
- [x] **Step4 GREEN:** same test command plus existing pricing/provider-policy tests. Expected all pass with unsupported configuration still explicitly unavailable, no external calls.
- [x] **Step5 Commit:** `feat(voice): define reviewed controlled Live cost and protocol contract`.

### Task 2: Reuse shared governor for connection and generation admission

**Files:** Create `voice/gemini_live_budget.py`, `tests/gemini_live/test_budget.py`; preserve legacy denial in `voice/gemini_budget.py` until actual controlled contract exists.

**Interfaces:** `ControlledLiveAdmission(runtime, *, session_id, authorize, contract: LiveModelContract)`; `async reserve(target, *, connection_id, trigger_id, exposure) -> ControlledLiveLease`. Lease `async .mark_dispatched()`, `.observe(event_id, raw_usage)`, `async .finish(complete: bool)`, `async .cancel_unsent()`, synchronous `.allow_frame(samples, sample_rate) -> bool`. Stable IDs/dedup remain backed by PaidBudgetGovernor; do not create another budget table. Admission source binds original session/epoch and only quota-authorized Paid target.

- [x] **Step1 RED tests:** reserve precedes actual client/connect/trigger; full35000 shared boundary with Work/Hands/memory; missing live price/FX/model/dimension denies; duplicate reserve/send/usage/restart one-shot; cancellation after dispatch/GoAway holds unknown; unsent cancellation only refunds; original source revoked during off-thread reserve cancels unsent and prevents send; no new provider health generation.
- [x] **Step2 Observe RED:** `PY -m pytest -o addopts= tests/gemini_live/test_budget.py -q`. Expected missing lifecycle/admission.
- [x] **Step3 Implement:** existing runtime price snapshot and governor; offload synchronous transaction with asyncio.to_thread, then revalidate authority before delivery. Every explicit continuation earns a separate reserve; final missing/ambiguous usage holds exposure. Reject overrun/unknown and halt new Paid input. No separate ledger or hidden probe.
- [x] **Step4 GREEN:** Task1/2 plus `tests/gemini_fallback/test_paid_budget.py`, pricing, concurrency/crash suites. Expected passing, no network.
- [x] **Step5 Commit:** `feat(voice): reserve controlled Live exposure through shared governor`.

### Task 3: Public Google Live transport and LiveKit stream/tool protocol

**Files:** Create `voice/gemini_live_{model,session,events}.py`, `tests/gemini_live/{test_public_transport,test_events,test_tools,test_activity}.py`; extend only public forwarding in `gemini_transport.py`.

**Interfaces:** `ControlledGeminiLiveModel(llm.RealtimeModel)` accepts exact target/voice/state/admission plus an injected public client factory (production key resolver is existing central owner). `.session(turn_detection_disabled=True) -> ControlledGeminiLiveSession`; public `.start_user_activity`, `.push_audio`, `.commit_audio`, `.generate_reply`, `.update_chat_ctx/tools/instructions`, `.interrupt`, `.truncate`, `.clear_audio`, `.aclose`.

- [x] **Step1 RED tests:** actual public model/session with fake `Client.aio.live.connect`; reserve exists before connect/setup/history/audio/end/text/tool response; client automatic VAD disabled, exact voice and supported options, no shared resumption handle; GoAway/read/setup failure does not retry/connect again; no video. Bound input30s and whole physical60s, queue overflow, disconnect idle after completed turn, next real turn fresh admission/canonical history. No response before an admitted trigger.
- [x] **Step2 RED event/tool tests:** process every part in a server event (audio+text+transcript+function), final vs provisional transcript, multiple/duplicate tool IDs, raw tool cancellation, exact matching pending tool results only, no replay of completed actions; reserve before blocking tool continuation. Real public GenerationCreatedEvent/MessageGeneration streams are consumed by AgentSession. Old epoch/private-source errors/audio/tool/transcript are fenced.
- [x] **Step3 Implement public transport:** one serialized command worker, bounded PCM queue/preroll160ms and explicit activity boundaries from existing local VAD. At most one public GenAI connect per physical transport; no automatic reconnect/resumption/compression. Keep same logical RealtimeSession between user turns; close physical paid socket on turn-complete/idle. Blocking tool wait retains socket only within60s and new response requires admission. Cache accepted context/config for next physical setup; revalidate before each disclosure. All recv parts processed, usage raw before SDK metrics normalization; missing final usage uncertain. Frame path only enqueues under an existing permit, no disk/provider work. Correctly fail pending futures/channels on close/cancel.
- [x] **Step4 GREEN:** `PY -m pytest -o addopts= tests/gemini_live tests/gemini_fallback/test_live_context.py tests/gemini_fallback/test_live_tool_replay.py -q`. Expected actual public event/AgentSession integration passes, fake network only.
- [x] **Step5 Commit:** `feat(voice): add admitted public Gemini Live transport adapter`.

### Task 4: Wire normal production failover and safe actual-demand Free recovery

**Files:** Modify `voice/{gemini_handoff,livekit_session,production_runtime,runtime}.py`, status if required; `tests/gemini_live/{test_production,test_handoff,test_recovery}.py`.

**Interfaces:** Real factory accepts only qualified `ControlledLiveAdmission/Lease` with matching Paid target+original state. Arbitrary budget objects/legacy unsupported paths still denied before key/client. Existing normal production session factory creates one GeminiLiveHandoff with the shared runtime, original guard and pre-registered event ordering. `_TransportAgent` sets public local VAD/endpoint0.8s only for controlled Paid model; Free keeps original options. Existing `.maybe_recover_free()` gets real local user-activity opportunity, defers speech/playback/tools and uses the one shared recovery fence.

- [x] **Step1 RED tests:** actual normal production factory OFF/Free unchanged; ON typed429 goes Free->Paid with exact key, same canonical session/bridge/tools/Authority/deadline, no new wake for accepted unanswered request.503/auth do not open Paid. Missing proof/key/price/budget/unknown fails safely. No startup/ephemeral voice bypass. Whole AgentSession local speech start/stop/end path drives public hooks with0.8s pauses and actual audio, not direct-only test helper calls.
- [x] **Step2 Observe RED:** `PY -m pytest -o addopts= tests/gemini_live/test_production.py tests/gemini_live/test_handoff.py tests/gemini_live/test_recovery.py -q`.
- [x] **Step3 Implement:** inject through existing production factory/observer/controller; replace unconditional Paid factory denial only for qualified controlled model. Register handler before resilience terminal close; retain public update_agent, physical epoch audio/input gates and original guards. Local idle holds no paid connection. Safe next actual demand tries Free once; rejected quota gives one bounded Paid visit, not repeated free probes. Paid402/auth updates same independent credential health. No extended-thinking/model switch/new settings activation.
- [x] **Step4 GREEN:** Tasks1-4 plus original voice/production/learning/context/resilience/TTS/ChatGPT tests. Expected no duplicate observer/tool/action and original Free regressions pass.
- [x] **Step5 Commit:** `feat(runtime): enable controlled Paid voice handoff on eligible quota pressure`.

### Task 5: Adversarial acceptance, performance evidence and one independent review

**Files:** Create `tests/gemini_live/{test_boundaries,test_crash,test_agent_session}.py`; product changes only for reproduced findings. Review scope begins atbbaa99d4, consumes prior structured-candidate evidence.

- [x] **Step1 Tests:** actual canonical temporary memory/Authority, lock/expiry/forget during every async reserve/setup/tool response; real AgentSession full-duplex/Hindi/Hinglish/English fictional transcripts and pause/barge-in; side-effect counters1 after accepted/uncertain actions. Real independent connections/processes contend with Work/Hands/memory for35000; process death after reserve/send/settle; source epoch never renewed. Exercise setup history and unexpected provider generation, truncated/partial usage, event races and bounded no-extra-wake continuation. No real OS side effect/model/provider inference.
- [x] **Step2 Run/repair:** `PY -m pytest -o addopts= tests/gemini_live tests/gemini_fallback tests/learning -q`. Passing new adversarial cases are additional evidence; any actual failure needs observed RED before minimal repair. Measure synthetic frame-queue/heartbeat overhead once, no flaky threshold or selective speed reruns.
- [x] **Step3 Independent review:** Native one fresh whole-amendment reviewer, spec/plan/diff/all Review Focus plus ledger; no implementation delegation. Regrade/ledger all findings and declined judgments before one Important/Critical RED-to-GREEN repair pass. No re-review; Minor deferred durably.
- [x] **Step4 Full GREEN:** isolated full repository pytest, Ruff check/format and diff whitespace. Expected passing actual counts/skips. Do not claim real provider quality/latency/ASR correctness or funding readiness from these tests.
- [x] **Step5 Commit:** `test(voice): verify controlled fallback concurrency privacy and action safety`.

### Task 6: Report, exact-head hosted checks and whole-app owner acceptance handoff

**Files:** Create `docs/research/GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md`; update previous candidate report/entrypoints/plan status around actual delivered/unsupported behavior.

- [x] **Step1 Report:** exact source/base/SDK/charging-contract/auxiliary-cost assumptions, all changed files/tests/rulings/costs/minors, actual performance limits, known vs unknown holds, persisted35000, dedicated keys/TTS/defaultOFF/rollback and actual model support. Preserve earlier semantic qualification deferrals.
- [ ] **Step2 Hosted:** push only this feature branch, update existing draftPR298; Linux/Windows/Hello/DPAPI and relevantSQLCipher on exact final head. No main/dependency merge; do not reusebbaa99d4 checks as proof of new Live code. Documentation-only head changes tracked honestly.
- [x] **Step3 Owner steps:** provide exact final fetch/switch/pull/launch with correct context/learning/paid modes. Real Paid experiment requires separate explicit request-count/duration/reviewed-INR-exposure approval and real price/FX. Whole normal app with fictional multilingual memory/actions; deterministic quota/recovery/402 harness, not burning real quota. No isolated microphone substitute. Actual spoken/model/Paid acceptance stays pending until observed.
- [ ] **Step4 Handoff:** retain branch/checkout and durable evidence; only own scratch may be cleaned after evidence/rulings preserved. No billing changes, activation or merge. Mark complete only behavior actually delivered; unsupported contract remains explicit rather than advertised as working.

Status at report commit: Task5 full receipt3177passed8skips; Task6 report and supported owner commands delivered. Hosted/publishing completion is recorded against the final docs-inclusive SHA in draftPR298. Paid launcher/accounting/spoken qualification remains explicitly pending; no Paid ON command is delivered.

## Self-review and preparation

Spec problem/alternatives -> Task1; admission/frame/protocol -> Tasks1-3; canonical/private/tool/Free recovery -> Tasks3-5; production -> Task4; acceptance -> Tasks5-6. All five Review Focus lines map to owning tests. Task1 contract/exposure is consumed by Task2 admission and Task3 config/usage; Task2 lease by Task3/4; Task3 public capabilities/hooks by Task4 real local VAD. No extra router/budget/memory authority. Inspect public SDK signatures before claiming compatibility; record any interface/proof conflict in this plan's own Native ledger.

Owner explicitly approved the next executable plan AND Native offline implementation in the design reply; method/boundaries are retained, so routine tasks do not require repeated permission. The plan is available for review while implementation continues; a genuinely unsupported charging contract or material scope change is ruled transparently rather than hidden.
