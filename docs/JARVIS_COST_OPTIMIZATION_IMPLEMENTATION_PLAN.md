# JARVIS Cost Optimization Implementation Plan

Status: **NEXT-CHAT IMPLEMENTATION PLAN / NOT IMPLEMENTED BY THIS DOCUMENTATION PR**

Date: 2026-09-29

Architecture source: `JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md`

## Slice C0 — Baseline and call inventory

Goal: establish current truth before changing routing.

- inventory all cloud/model call sites: voice realtime, scripted TTS, work reasoner, Hands, memory, research synthesis and other provider adapters;
- classify each call as deterministic-avoidable, local-candidate, cheap-cloud-candidate, strong-cloud-candidate or voice-specific;
- identify current usage metadata available from each provider/adapter;
- create a baseline cost/latency schema without changing owner Authority.

Exit:
- every relevant current model path is mapped to one owner-visible inventory;
- no unknown paid path remains in the experiment scope.

## Slice C1 — Cost telemetry foundation

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

Goal: determine whether Jev reduces total cost without becoming a fragile dependency.

Build a JARVIS-specific decision benchmark covering:

- route selection;
- task classification;
- tool/capability choice among approved options;
- retry/escalate;
- web-research-needed;
- local-vs-cloud;
- cheap-vs-strong cloud.

Compare:

- deterministic-only baseline;
- Jev;
- small local classifier/model;
- existing general LLM where appropriate.

Measure:

- decision accuracy;
- calibration/confidence usefulness;
- latency;
- cost;
- outage/fallback behavior;
- downstream expensive calls avoided.

Rules:

- Jev never grants Authority;
- deterministic policy outranks Jev;
- local/deterministic fallback is mandatory;
- re-verify Jev service/pricing/terms before integration.

Exit:
- adopt only if it saves expected mission cost and meets accuracy/latency thresholds;
- otherwise defer without blocking the rest of the program.

## Slice C5 — Local Brain benchmark and admission

Goal: create a useful zero-API reasoning tier.

Research current local runtimes/models fresh at implementation time.

Benchmark on the owner's machine against the JARVIS task corpus.

Model admission is task-specific. A model can be accepted for summarization and classification while rejected for architecture or hard debugging.

Exit:
- at least one local target is registered with measured capabilities;
- router sends only accepted task classes to it;
- low-confidence/failed local work escalates cleanly.

## Slice C6 — Retrieval/context optimization

Goal: make local and cloud reasoning cheaper and more reliable.

- reuse EngineeringKnowledge and existing local retrieval;
- retrieve relevant repo/docs/log/memory evidence instead of copying broad histories;
- bound context per task;
- cache/reuse verified stable evidence when freshness permits;
- retain provenance and freshness metadata.

Exit:
- benchmark demonstrates reduced context size without unacceptable answer/decision degradation.

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
