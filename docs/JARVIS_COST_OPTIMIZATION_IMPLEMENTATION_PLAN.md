# JARVIS Cost Optimization Implementation Plan

Status: **C0-C3 LIVE ACCEPTED / C4 DEFERRED / C5 RETAINED AS ON-DEMAND FALLBACK / C6 SHADOW ACTIVE / CHATGPT-PLAN PRIMARY BRAIN OWNER-MACHINE ACCEPTED**

Date: 2026-09-30

Architecture source: `JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md`



## Architecture update — ChatGPT-plan primary brain (2026-09-30)

Fresh OpenAI Sign in with ChatGPT plan-usage support changes the cost hierarchy without
discarding C0-C6.

New production intent after owner acceptance:

1. deterministic JARVIS logic/cached knowledge where sufficient;
2. ChatGPT-plan OAuth inference as the primary strong reasoning lane for durable Work and
   Hands semantic planning;
3. the currently configured Gemini/OpenAI API provider as bounded fallback;
4. the C5 local Ollama/Qwen target retained only as an optional on-demand/offline lane,
   never a 24x7 resident production brain.

Consequences:

- C5 is not removed; its benchmark, admission and resource-pressure work remains useful,
  but JARVIS must not occupy several GiB of owner GPU memory merely to avoid cloud calls.
- C6 context optimization remains valuable because plan-backed Responses calls are
  stateless over normal HTTP and JARVIS owns the relevant context projection.
- Realtime voice/TTS stay on their existing provider-specific path because ChatGPT-plan
  token sharing is not a substitute for the realtime/audio APIs.
- ChatGPT OAuth access/refresh tokens live only in the existing encrypted SecretStore.
  Machine config persists only the enable flag and selected model slug.
- Plan-backed Responses requests use store=false and stream=true, validate terminal
  completion, and expose usage telemetry.
- ChatGPT plan quota/auth/model failures are provider failures, not authority failures:
  Work falls back through the existing health/router substrate and Hands uses its bounded
  configured paid-provider fallback.
- The production Work target pool does not contain the C5 local LLM when ChatGPT-plan
  primary routing is enabled.
- Paid API credits are no longer a prerequisite for the first TV capability mission.
  First prove the plan-backed lane on the owner machine; buy/use paid credits only if
  plan availability or an unsupported capability actually requires them.

Owner-machine acceptance completed successfully on 2026-09-30 and PR #234 was
squash-merged to protected `main` as
`566705afa1e8c2650c57d5bc26ee369c25f5aacc`.

Acceptance proved:

- browser OAuth completed against the owner's ChatGPT account;
- the required plan-usage scope was granted and persisted in encrypted SecretStore;
- account-visible model discovery succeeded;
- `gpt-6-astra` was selected from the returned account-visible catalog;
- a live subscription-backed Responses structured-inference probe completed;
- observed usage for that acceptance inference was 82 input + 30 output = 112 tokens;
- durable Work primary routing resolved to `work.chatgpt_plan.default`;
- the bounded paid fallback remained `work.gemini.default`;
- the production Work pool contained no local LLM target.

This closes the ChatGPT-plan provider acceptance gate. The next validation target is a
real Phase-9 external capability mission, using the TV control request to prove the
previously deferred research -> architecture -> development -> promotion -> activation ->
physical effect -> observation -> disable/rollback lifecycle.

## Research validation checkpoint — 2026-09-29

Fresh repository inspection and current-tooling research refine the execution order without changing the architecture.

Confirmed current-state facts:

- Phase 4 already provides `CostProfile`, `RoutingAttempt.usage`, `RoutingAttempt.estimated_cost_usd`, `RoutingOutcome.aggregate_usage`, `RoutingOutcome.estimated_total_cost_usd` and durable routing storage. C1 should extend these contracts rather than create a separate cost database.
- Current Gemini/OpenAI structured-output adapters return only the validated model result; provider usage metadata is not yet propagated into the routing attempt. C1 should introduce one provider-neutral invocation result/envelope carrying parsed output plus usage/latency metadata.
- Current realtime voice creates the cloud realtime model directly and resolves the same provider credential family used elsewhere. This confirms that C2 credential/billing separation is necessary before paid-brain testing.
- The current Phase-4 work router is already the correct substrate to evolve. It presently creates cloud Gemini/OpenAI work targets; C3 should generalize this registry/router to deterministic, local and tiered-cloud paths rather than introduce a second router.
- Background autonomous work should be the first subsystem to adopt cost-aware routing. Realtime voice should move later because latency and conversational UX make it the highest-risk place to optimize first.
- Local-model admission must remain benchmark-driven on the owner's RTX 5060 Ti 8 GB / 16 GB RAM machine. Start with a small efficient Qwen 3.5-class model and test a larger quantized tier only if hardware measurements justify it; no model is globally trusted merely because it fits.
- Jev remains an optional bounded decision-layer candidate. Benchmark it against deterministic logic and a small local decision model; adoption is not a prerequisite for the rest of the program if evidence does not justify it.
- Current cloud model pricing changes quickly. C7 must populate dated cost profiles from provider pricing at implementation time rather than hard-code today's prices into permanent routing logic.

### Refined execution sequence

Implement in this order:

1. **C0 + C1 together — inventory and observability.**
2. **C2 — TTS/paid-brain credential separation.**
3. **C3 — Global Brain Router v1 using the existing Phase-4 substrate.**
4. **C4 + C5 — benchmark bounded decision and local-brain tiers.**
5. **C6 + C7 — context reduction and genuinely distinct cloud tiers.**
6. **C8 + C9 — gradual subsystem adoption and pre-credit acceptance.**
7. **C10 — instrumented ₹400–₹500 blind TV capability experiment.**
8. **C11 — Cost Governor only after real mission economics exist.**

Do not begin by changing the preferred voice, buying additional development subscriptions, or searching indefinitely for a perfect local model. First make every relevant intelligence call visible and attributable.

## Slice C0 — Baseline and call inventory

Status: **COMPLETE** — authoritative inventory: `JARVIS_COST_CALL_INVENTORY.md`.

Goal: establish current truth before changing routing.

- inventory all cloud/model call sites: voice realtime, scripted TTS, work reasoner, Hands, memory, research synthesis and other provider adapters;
- classify each call as deterministic-avoidable, local-candidate, cheap-cloud-candidate, strong-cloud-candidate or voice-specific;
- identify current usage metadata available from each provider/adapter;
- create a baseline cost/latency schema without changing owner Authority.

Exit:
- every relevant current model path is mapped to one owner-visible inventory;
- no unknown paid path remains in the experiment scope.

## Slice C1 — Cost telemetry foundation

Status: **IMPLEMENTED / ACCEPTANCE TESTED**.

Implemented foundation:

- provider-neutral normalized usage telemetry for routed Gemini/OpenAI structured calls;
- durable non-token provider cost events for request/page/audio/tool-style charges;
- durable provider/model/stage/usage/retry/cost provenance on routing attempts;
- explicit missing-usage and unpriced states rather than false zero cost;
- WorkItem and EngineeringChange mission-level aggregation;
- deterministic provider-usage, cost-estimation and aggregation tests;
- routed dry-run Work mission coverage proving a mission cost report can be produced;
- background Exa research accounting that rolls dated search/content request estimates into the same Work mission total.

Goal: measure before spending.

- extend/reuse Phase-4 RoutingAttempt/Outcome cost provenance;
- capture provider/model usage, stage, retries, latency and cost estimate;
- aggregate per WorkItem/EngineeringChange/mission;
- redact secrets and avoid raw sensitive prompt persistence;
- make missing provider usage explicit rather than silently assuming zero.

Exit:
- deterministic tests prove aggregation;
- a dry-run mission can produce a cost report even when estimated cost is zero/mock.

## Slice C2 — Voice/TTS billing separation

Status: **IMPLEMENTED / ACCEPTANCE TESTED**.

Implemented foundation:

- `JARVIS_AI_PROVIDER` remains the brain/realtime reasoning selector;
- `JARVIS_TTS_PROVIDER` independently selects scripted lifecycle TTS and defaults to the preferred Gemini path;
- dedicated `JARVIS_TTS_GOOGLE_API_KEY` / `JARVIS_TTS_OPENAI_API_KEY` credentials take precedence over legacy shared provider keys;
- dedicated credentials are treated only as **credential isolation**, never proof of billing isolation;
- `JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED` is the explicit owner attestation required by the paid-experiment gate after verifying the TTS project in AI Studio/Cloud Billing;
- legacy shared-key fallback is retained only for migration/compatibility so the current voice does not break immediately;
- preflight reports whether the TTS lane is dedicated, compatibility/shared, or local-fallback-only;
- provider CLI can inspect both lanes and switch scripted TTS without changing the brain provider;
- missing cloud TTS credentials remain non-fatal because the existing Windows-local lifecycle speech fallback is preserved;
- scripted Gemini TTS defaults to current `gemini-3.8-flash-tts` while preserving Charon; `gemini-3.8-flash-lite-tts` can be selected through `JARVIS_GEMINI_TTS_MODEL` for later A/B evaluation;
- deterministic tests prove that changing the brain provider cannot redirect scripted TTS.

Pre-paid experiment requirement: configure a **dedicated** TTS credential **and verify that its project is billing-isolated at the Google project level** before using paid-brain credits. A different API key alone is not sufficient.

Goal: protect the paid-brain experiment from routine voice-output consumption without changing preferred voice UX.

- separate configuration/secret references for TTS versus paid reasoning;
- retain current preferred Gemini TTS path while legitimate free-tier service is available;
- retain local Windows speech fallback;
- ensure reasoning-provider changes cannot accidentally redirect scripted speech onto the paid-brain credential;
- do not change the JARVIS voice merely for cost reduction.

Exit:
- scripted TTS and paid-brain reasoning can be independently configured;
- provider failure still falls back locally;
- no paid-brain credential is required for routine configured free-tier TTS.

## Slice C3 — Global Brain Router v1

Status: **IMPLEMENTED / OWNER-MACHINE ACCEPTED / LIVE APPLY**.

Research source: `JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md`.

Implementation source: `JARVIS_C3_GLOBAL_BRAIN_ROUTER_IMPLEMENTATION.md`.

Implemented foundation:

- subsystem-neutral `GlobalBrainRouteFacts` contract;
- thin `GlobalBrainRouterReasoner` around the existing Phase-4 `RoutedWorkReasoner`;
- versioned fail-closed deterministic resolver registry;
- durable route provenance and per-Work model-calls-avoided summary;
- rollout modes `off`, `shadow` (default), and explicit `apply`;
- exact deterministic Work rules for initial development workspace preparation,
  initial diagnostic incident inspection, and verified post-test diff inspection;
- ambiguous/missing deterministic matches abstain to the existing model path;
- unapproved deterministic actions fail closed;
- durable replay pins an already-persisted Phase-4 model route to the model path;
- full WorkEngine acceptance proves deterministic execution still passes through the
  governed executor while model reasoning is bypassed;
- a non-engineering memory fixture proves the same global facts can feed the existing
  ModelRouter without redesigning the routing substrate;
- JARVIS Self Model now explicitly maps `work.brain_routing`.

Repository default remains **shadow** for new/unaccepted machines. The owner's accepted
production machine is explicitly configured to **apply**, and live startup has proven
`brain_router_mode=apply` with Work orchestration active.

Architecture decision:

- one logical routing pipeline with a thin intelligence-path policy in front of the existing Phase-4 ModelRouter;
- deterministic path selects only an already-approved `BrainDecision`; execution remains in the governed Work/Hands/capability runtime;
- deterministic resolvers are versioned, explicit and must abstain on ambiguity;
- bounded-decision slot is reserved for C4 but disabled in C3;
- local/cloud target selection continues through the existing ModelTarget registry, eligibility, health, strategy and fallback substrate;
- add durable route provenance for deterministic bypasses so avoided model calls are measurable;
- start with shadow evaluation, then apply only replay-accepted deterministic rules;
- do not adopt LiteLLM, vLLM Semantic Router, Not Diamond or another gateway as the C3 core.

Initial deterministic Work rules now implemented:

- development initial workspace preparation;
- diagnostics initial canonical incident inspection;
- post-test development diff inspection when canonical state proves it is required.

Acceptance evidence:

- deterministic `WorkEngine.advance()` cycle executes the normal governed WorkStep
  with zero model-reasoner calls;
- shadow mode preserves the current model decision and records match/mismatch;
- `off` mode does not execute deterministic resolvers;
- ambiguity falls back to the existing model path;
- route provenance survives/replays consistently;
- existing Phase-4 routing, Windows Phase-6/7/8/9 regressions and promotion policy pass.

Goal: generalize the existing Phase-4 router rather than create another router.

Add a global request contract that captures:

- task/subsystem;
- required capabilities;
- locality/privacy;
- latency sensitivity;
- context size;
- available deterministic capability;
- available verified/cached knowledge;
- previous attempts/failures;
- required output contract;
- quality/escalation class.

Routing order:

1. deterministic/known capability;
2. bounded decision layer if needed;
3. local reasoning;
4. cheap cloud;
5. standard/strong cloud;
6. owner/blocker when no approved economical route exists.

Preserve:

- target registry;
- eligibility;
- health/cooldown;
- bounded fallback;
- strategy versioning;
- provenance;
- Authority independence.

Exit:
- existing Phase-4 engineering routing still works;
- at least one non-engineering path can use the same global substrate;
- deterministic execution can bypass model invocation entirely.

## Slice C4 — Jev decision-layer evaluation

Status: **RESEARCH COMPLETE / JEV DEFERRED**.

Research source: `JARVIS_C4_C5_BOUNDED_LOCAL_BRAIN_RESEARCH.md`.

Decision:

- the frozen 18-case bounded-decision corpus and shared scorer remain available;
- Jev is not required for the current cost-optimization architecture;
- C5 proved that a task-scoped local tier is already useful without adding Jev;
- deterministic policy remains first and model routing remains the fallback;
- revisit Jev only if later measured mission economics show a real gap in routing
  accuracy/cost that the deterministic/local layers do not solve.

Jev must never grant Authority or bypass owner/safety gates if revisited.

Exit: **met by evidence-based deferral**. C4 does not block C6-C10.

## Slice C5 — Local Brain benchmark and admission

Status: **FULLY COMPLETE / OWNER-MACHINE ACCEPTED**.

Research source: `JARVIS_C4_C5_BOUNDED_LOCAL_BRAIN_RESEARCH.md`.

Final implementation and acceptance:

- runtime: Ollama;
- selected model: `qwen3.5:4b` with `think=false`;
- final frozen-corpus semantic score approximately 76.92%, versus approximately
  70.77% for Phi-4-mini;
- selected local admission is task-scoped, not universal;
- admitted task classes:
  - `bounded_planning`;
  - `classification_extraction`;
  - `summarization`;
- explicitly not admitted:
  - engineering code generation;
  - debugging;
  - architecture;
  - deep research;
  - unknown/unclassified work;
- production ModelInvoker/Ollama integration uses structured JSON/Pydantic validation,
  provider-neutral telemetry, zero local token API cost and safe fallback;
- malformed structured local output is classified as `response_contract_invalid`
  so approved fallback can continue;
- local GPU pressure is classified as `local_resource_pressure` so the router does
  not retry the same GPU model while the owner is gaming;
- replay compatibility is preserved with an isolated C5 local target registry rather
  than mutating old durable Work target-registry digests;
- live JARVIS voice/vision coexistence passed;
- warm owner-machine invocations were approximately 279-302 ms after load;
- Qwen residency adds approximately 3.8-3.9 GB VRAM;
- Qwen is not kept permanently resident.

Production residency policy:

- cold load only when free VRAM >= 5600 MiB and GPU utilization <= 45%;
- if resident, evict after two consecutive 2-second samples when free VRAM <= 1800 MiB
  or GPU utilization >= 80%;
- emergency evict on the first sample when free VRAM <= 1200 MiB;
- recover only after free VRAM >= 5600 MiB and GPU utilization <= 35% for three calm
  samples;
- active local inference is protected from self-eviction;
- stale residency assumptions expire before Ollama's keep-alive can silently invalidate
  them.

Merged PRs:

- #229 — semantic admission;
- #230 — production Ollama integration;
- #231 — live JARVIS/Qwen coexistence;
- #232 — resource-aware residency.

Accepted C5 main:
`562d7dcc08d33db0626c7c305a9cf40fe14b3f08`.

Exit: **met**. Do not reopen C5 or benchmark 9B merely because larger models exist.

## Slice C6 — Retrieval/context optimization

Status: **SHADOW IMPLEMENTATION ACTIVE / PRODUCTION PROVIDER PAYLOAD STILL LEGACY**.

Research source: `JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md`.

Repository finding:

- `WorkEngine` currently reads the full canonical Work history and passes
  `steps[-12:]` into `BrainRequest`;
- `_work_input_payload()` serializes each supplied step's input, observation and error
  plus all supplied evidence;
- this makes large file reads, diffs, test logs and repeated observations an immediate
  context-cost target.

C6 architecture:

- keep `SQLiteWorkStore` as complete durable truth;
- introduce a bounded deterministic `ContextPack` projection for model context only;
- preserve routing/replay identity from canonical Work progress;
- retain task/stage-critical milestones rather than blindly selecting the last N full
  objects;
- bound large strings/lists and retain hashes/provenance so omission is explicit;
- expose an omitted-step manifest rather than treating omitted history as nonexistent;
- optionally adapt existing EngineeringKnowledge retrieval only when a trustworthy
  applicability context exists;
- EngineeringKnowledge remains advisory and cannot mint Authority;
- do not add a vector database or second retrieval framework.

Implemented shadow foundation:

- `src/jarvis/work/context.py` — deterministic bounded step selection, compaction,
  provenance manifest and context-size telemetry;
- `src/jarvis/work/context_knowledge.py` — optional conservative
  EngineeringKnowledge adapter;
- `src/jarvis/work/context_evaluation.py` — strict decision-equivalence scorer for
  action, parameters, completion and owner-escalation fields;
- WorkEngine now assembles a ContextPack in shadow by default;
- WorkReasoner measures legacy versus optimized payloads but sends the exact legacy
  payload while mode is `shadow`;
- routing context-size estimates change only in `apply`; replay/progress signals remain
  based on canonical recent WorkSteps;
- deterministic C6 unit coverage and a zero-cloud real Work-history owner acceptance
  harness are included.

Rollout modes:

- `off` — legacy only;
- `shadow` — build/measure optimized context, send legacy context;
- `apply` — optimized model context.

Current production intent: **shadow only**. Do not enable `apply` until benchmark and
owner-machine evidence show meaningful context reduction without unsafe decision
degradation.

Acceptance path:

1. CI/unit equivalence and context-bound tests;
2. owner-machine zero-cloud history probe using
   `tools/research/c6_context_owner_acceptance.py`;
3. real shadow observation;
4. paired legacy/optimized decision-equivalence benchmark;
5. only then consider C6 apply.

Exit:
- benchmark demonstrates material context reduction;
- action/parameters/`goal_complete`/`needs_owner`/owner-question equivalence meets
  the acceptance bar;
- no Authority, replay or completion-guard regression.

## Slice C7 — Cheap/strong cloud tier correction

Goal: make route roles economically meaningful.

- define genuinely distinct cheap, normal and strong target profiles;
- populate/refresh cost profiles from current provider pricing;
- make cost preference effective after hard capability/privacy/health eligibility;
- preserve affinity only where continuity value justifies it;
- keep strong-model escalation evidence-driven.

Exit:
- easy accepted tasks route to cheaper targets;
- hard/evidence-conflicted tasks can escalate;
- tests prove provider pressure does not masquerade as reasoning difficulty.

## Slice C8 — Subsystem adoption

Adopt global routing gradually:

1. background work/capability acquisition;
2. memory model calls;
3. Hands planning;
4. research synthesis;
5. voice lifecycle/simple known commands;
6. broader voice only after latency/UX evidence.

Do not force one policy across all subsystems. Voice can prioritize latency; engineering can prioritize correctness.

Exit:
- each adopted subsystem has its own acceptance metrics and rollback path.

## Slice C9 — Pre-credit acceptance

Before spending paid experiment money, prove:

- TTS and paid-brain credentials are separated;
- cost telemetry works;
- global router works;
- at least one local target is admitted;
- Jev is adopted or explicitly deferred from evidence;
- cheap/strong cloud tiers are real;
- bounded fallback/escalation works;
- no owner Authority regression;
- no unacceptable voice UX regression.

## Slice C10 — ₹400–₹500 blind capability experiment

Only after C9:

- fund paid-brain project with approximately ₹400–₹500;
- run the blind TV capability mission;
- do not leak known TV IP/protocol/port/library clues;
- allow legitimate owner pairing/physical confirmation;
- collect stage-by-stage cost and outcome evidence;
- stop or owner-gate if experiment budget threshold is reached.

Exit report:

- autonomy result;
- physical capability result;
- cost by stage/model;
- local-vs-cloud share;
- retries/fallbacks;
- latency;
- next optimization selected from evidence.

## Slice C11 — Cost Governor

Implement only after real cost data exists.

- monthly/daily/mission budgets;
- retry and strong-model budgets;
- owner escalation thresholds;
- durable budget state;
- fail-closed behavior;
- explicit emergency/owner overrides if later approved.

## Optional Claude development worker

Claude Code/subscription-backed development may be evaluated in parallel as an optional engineering worker.

It is not required for C0–C10 and must not become a hidden dependency.

Before use, re-verify current Anthropic subscription/Agent SDK terms and distinguish subscription usage from API-billed usage.

## Testing philosophy

Every slice must include:

- deterministic unit/contract tests;
- restart/persistence tests where state is durable;
- negative controls;
- provider-unavailable behavior;
- cost-accounting correctness;
- no Authority weakening;
- rollback/disable path.

No optimization is accepted solely because it is cheaper. It must preserve required correctness, latency, UX and governance.
