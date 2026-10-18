# Phase 4 Implementation Plan — Research + Diagnostic Model Router

Status: **DONE / OWNER-MACHINE ACCEPTED 2026-09-26**

Research: `PHASE4_MODEL_ROUTER_RESEARCH.md`  
Architecture: `PHASE4_MODEL_ROUTER_ARCHITECTURE.md`

Permanent engineering rule:

`research thoroughly -> architecture -> owner approval -> isolated branch/PR -> CI -> owner-machine acceptance when required -> docs -> merge`

## Goal

Implement the approved provider/model-neutral routing boundary for background engineering reasoning without changing Authority, WorkItem, EngineeringChange, research evidence, verification, sandbox or protected-main ownership.

The first production consumer is the durable WorkReasoner path.

## Global constraints

- No realtime voice/conversation routing in this phase.
- No Jev implementation.
- No mandatory LiteLLM/OpenRouter/Portkey/vLLM/Switchyard server or proxy.
- No new paid routing service.
- No unrestricted provider/model registration.
- No plaintext secrets in routing persistence.
- No cross-provider fallback to evade content/policy rejection.
- No learned/history-driven production routing before benchmark acceptance.
- Preserve existing `BrainDecision` behavior where possible.
- Preserve interactive voice priority over background reasoning.
- Preserve DBOS and canonical WorkItem identity.
- Every schema/strategy/adapter version must fail closed when unknown.

---

## 4A — Canonical routing models and registries

**Create**

- `src/jarvis/model_routing/__init__.py`
- `src/jarvis/model_routing/models.py`
- `src/jarvis/model_routing/registry.py`
- `tests/test_model_routing_models.py`
- `tests/test_model_routing_registry.py`

**Implement**

- `ModelTarget`
- locality/privacy enums or registered keys
- capability/role metadata
- `RoutingRequest`
- `EligibilitySnapshot`
- `RoutingDecision`
- `RoutingAttempt`
- `RoutingOutcome`
- `ModelTargetRegistry`
- `ModelAdapterRegistry`
- `RoutingStrategyRegistry`

**Tests**

- stable target identity;
- duplicate target rejection;
- unknown adapter/strategy fail closed;
- target schema validation;
- no credential plaintext field;
- future local target can register without changing core schema;
- strategy output can order more than two candidates.

**Exit**

All pure contracts are deterministic and provider-neutral.

---

## 4B — Deterministic eligibility policy

**Create**

- `src/jarvis/model_routing/eligibility.py`
- `tests/test_model_routing_eligibility.py`

**Implement hard filters**

- enabled/disabled;
- approved benchmark status;
- capability support;
- context capacity;
- structured-output requirement;
- locality/privacy;
- credential availability;
- adapter availability;
- target-health availability;
- required route role/profile.

**Tests**

- `LOCAL_ONLY` can never select cloud;
- missing capability excludes target;
- missing credential excludes target without revealing secret;
- context overflow excludes target;
- all targets excluded returns typed no-route result;
- strategy cannot reintroduce an excluded target;
- eligibility output includes reason codes and policy digest.

**Exit**

All safety/technical eligibility is owned by deterministic JARVIS code.

---

## 4C — Routing persistence and target health

**Create**

- `src/jarvis/model_routing/store.py`
- `src/jarvis/model_routing/health.py`
- `tests/test_model_routing_store.py`
- `tests/test_model_routing_health.py`

**Modify**

- existing WorkStore schema/migration boundary only as required.

**Implement**

- additive routing tables sharing the existing WorkStore connection/codec;
- append-only decision/attempt records;
- target-health CAS/versioning;
- cooldown expiry;
- provider failure -> health action mapping;
- strategy/registry/policy digest persistence.

**Tests**

- encrypted/protected sensitive payload handling where applicable;
- transaction rollback fault injection;
- concurrent health update CAS;
- 429 -> target cooldown;
- 503/timeout/connection -> bounded transient handling;
- auth/model configuration -> target unavailable;
- policy/content rejection -> no cross-provider fallback;
- cooldown expiry;
- persistence restart round-trip.

**Exit**

Routing operational truth is durable without a new database.

---

## 4D — Initial `engineering_stage.v1` strategy

**Create**

- `src/jarvis/model_routing/strategy.py`
- `tests/test_model_routing_strategy.py`

**Implement**

- WorkStep-derived progress/failure signals;
- efficient/capable initial role profiles;
- capable escalation;
- bounded hold/affinity recommendation;
- deterministic ordered candidate output;
- provider-pressure excluded from task-difficulty scoring.

**Tests**

- settled/mechanical work prefers efficient;
- repeated quality failures escalate capable;
- provider 429 alone does not classify task as harder;
- unknown diagnostic work can prefer capable;
- healthy progress can de-escalate;
- strategy output remains deterministic for same snapshot;
- future third role/target does not require schema change.

**Exit**

The first router strategy is deterministic, explainable and WorkStep-aware.

---

## 4E — Provider-neutral invocation and RoutedWorkReasoner

**Create**

- `src/jarvis/model_routing/invoker.py`
- `src/jarvis/model_routing/router.py`
- `tests/test_routed_work_reasoner.py`

**Modify**

- `src/jarvis/work/reasoner.py`
- `src/jarvis/work/runtime.py`
- provider adapter boundary only where required.

**Implement**

- adapter wrappers around existing OpenAI/Gemini structured-output clients;
- `ModelRouter.route(...)`;
- `RoutedWorkReasoner`;
- one canonical reasoning-cycle key;
- route decision before invocation;
- structured `BrainDecision` unchanged where feasible;
- correlation/idempotency metadata where supported.

**Tests**

- current Gemini path still works through adapter;
- current OpenAI path works through adapter;
- router selects target before invocation;
- target adapter does not choose routing;
- same reasoning cycle does not create duplicate route decision;
- interactive voice preemption still works;
- no change to direct Hands/realtime provider behavior.

**Exit**

Background work no longer depends on one globally fixed reasoning provider.

---

## 4F — Bounded fallback and blocker semantics

**Modify**

- `src/jarvis/model_routing/router.py`
- `src/jarvis/work/engine.py` only as narrowly required;
- existing provider-pressure flow as required.

**Implement**

- bounded fallback chain;
- failed-target exclusion within the chain;
- cooldown persistence;
- retry/fallback reason codes;
- same WorkItem identity throughout;
- fallback exhaustion -> truthful `WAITING_RESOURCE`/blocked state and delivery;
- sustained pressure escalation notification;
- no fallback for policy/content rejection.

**Tests**

- Gemini 429 -> target cooldown -> approved OpenAI fallback;
- fallback retains WorkItem ID;
- no duplicate EngineeringChange;
- fallback chain stops at configured budget;
- all targets unhealthy -> waiting/blocker;
- content-policy rejection -> fail closed/no provider hopping;
- restart during fallback resumes lineage without duplicate decision/attempt.

**Exit**

The Phase-3 Gemini-429 class of problem is handled by target-aware routing instead of indefinite single-target retry.

---

## 4G — Routing outcome/provenance and status

**Create/Modify**

- `src/jarvis/model_routing/store.py`
- status/read interfaces;
- narrow self-awareness/status exposure if useful.

**Implement**

- bounded route status for owner inspection;
- selected target + reason codes;
- fallback path;
- health state;
- latency/usage/cost estimate;
- independent verification reference when available;
- explicit unknown/unavailable metrics rather than invented values.

**Tests**

- status contains no secrets;
- missing usage/cost remains unknown;
- route provenance references WorkItem/change/stage;
- model/router confidence is never presented as verification success.

**Exit**

Routing is inspectable and truthful.

---

## 4H — Evaluation and shadow benchmark

**Create**

- `src/jarvis/model_routing/evaluation.py`
- `tests/test_model_routing_evaluation.py`
- JARVIS-specific bounded evaluation fixture/cases.

**Baselines**

1. current fixed production target;
2. always-capable;
3. always-efficient;
4. `engineering_stage.v1`.

**Measure**

- verified success;
- structured-output validity;
- fallback recovery;
- wrong-route/regret proxy;
- unnecessary escalation;
- model-call count;
- latency;
- tokens/usage;
- estimated cost;
- route churn;
- results by task category.

**Rules**

- no learned strategy enters production;
- no history-based preference enters production merely because telemetry exists;
- evaluation outcome does not self-promote routing policy;
- benchmark artifacts are reproducible and source/model versions are recorded.

**Exit**

The deterministic stage router has objective evidence against fixed baselines.

---

## 4I — Owner-machine acceptance and documentation

**Create**

- `src/jarvis/model_routing/acceptance.py`
- `docs/PHASE4_MODEL_ROUTER_OWNER_ACCEPTANCE.md`

**Update after evidence**

- `docs/CURRENT_ARCHITECTURE.md`
- `docs/CURRENT_PLAN.md`
- `docs/PROJECT_STATE.md`

**Live acceptance sequence**

1. start from exact green PR head;
2. confirm target registry and active strategy;
3. launch one bounded background engineering WorkItem;
4. inspect real routing decision/provenance;
5. demonstrate target health/fallback using a safe controlled method where practical;
6. confirm same WorkItem/EngineeringChange identity after fallback;
7. confirm no Authority/Windows Hello/approval behavior changed;
8. restart runtime during a routed WorkItem and confirm same route lineage resumes;
9. run acceptance evidence CLI;
10. record final owner disposition before merge.

**Required CI**

- Ruff;
- full pytest;
- existing Windows Hello helper;
- existing Windows DPAPI;
- all routing tests;
- no protected-main or secret regression.

**Exit**

Phase 4 becomes DONE only after green CI and the documented owner-machine acceptance boundary is satisfied.

---

## Explicitly deferred after Phase 4

These are not blockers for Phase 4 completion:

- Jev optimization experiment;
- learned router trained from JARVIS outcomes;
- native Switchyard embedding;
- LiteLLM proxy/router adoption;
- realtime voice model routing;
- local model installation;
- specialist model curriculum/training;
- autonomous routing-policy self-modification.

Each can be added later through the Phase-4 target/adapter/strategy/evaluation interfaces.

## Implementation completion definition

**Satisfied on 2026-09-26.**

JARVIS now truthfully and durably chooses among approved background reasoning targets using deterministic eligibility + stage routing, survives provider pressure through bounded target-aware fallback, preserves canonical WorkItem identity, exposes route provenance, and has passed benchmark, restart-continuity and Authority/security owner-machine acceptance.

Canonical acceptance record: `PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md`.

No later phase should need to replace this core boundary to add local, specialist, learned or Jev-backed routing.
