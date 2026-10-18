# Phase 4 Architecture — Research + Diagnostic Model Router

Status: **OWNER-APPROVED ARCHITECTURE / READY FOR IMPLEMENTATION**

Research basis: `PHASE4_MODEL_ROUTER_RESEARCH.md`

## 1. Goal

Create one stable provider/model-neutral routing boundary for JARVIS background engineering intelligence.

The router selects an approved reasoning target for bounded research synthesis, diagnostics and engineering reasoning while preserving all existing Authority, WorkItem, EngineeringChange, verification, sandbox, credential and protected-main boundaries.

Phase 4 is not a generic AI gateway and not a provider-failover patch. It is the model-selection substrate for the autonomous-engineering end state.

## 2. Non-goals

Phase 4 does not:

- route realtime voice/conversation sessions in the first production slice;
- replace Exa or current research evidence contracts;
- create a second task/orchestration system;
- grant or lower Authority;
- manage plaintext secrets;
- merge/deploy/promote code;
- perform unknown-incident source repair itself;
- install arbitrary local models;
- use learned routing in production without JARVIS-specific evaluation;
- implement Jev.

## 3. Permanent invariants

1. **Routing never changes Authority.**
2. **Hard eligibility is deterministic JARVIS code.**
3. **A model cannot declare itself eligible.**
4. **Privacy/locality requirements are hard constraints, not scoring preferences.**
5. **Provider/model health affects target availability, not permissions.**
6. **Policy/content rejection is not ordinary availability failure and cannot trigger provider hopping to evade policy.**
7. **Routing confidence is not verification truth.**
8. **Routing output is advisory execution selection; WorkItem/EngineeringChange remain canonical lifecycle truth.**
9. **Secrets are referenced by handles/config availability only; plaintext secrets do not enter route records.**
10. **Every production route is explainable from a versioned strategy + immutable/snapshotted input facts.**
11. **Fallback is bounded.**
12. **Unknown target/strategy versions fail closed.**
13. **Adding future local/specialist providers must be additive behind adapters.**
14. **Historical outcomes can influence routing only after independent verification and explicit policy adoption.**

## 4. Package boundary

Initial implementation lives under:

`src/jarvis/model_routing/`

Recommended modules:

- `models.py`
- `registry.py`
- `eligibility.py`
- `strategy.py`
- `health.py`
- `store.py`
- `router.py`
- `invoker.py`
- `evaluation.py`
- `acceptance.py`

The first production integration point is `jarvis.work.reasoner`.

Existing Hands, realtime voice and memory provider paths remain unchanged unless a later separately approved phase adopts the routing boundary.

## 5. Canonical objects

### 5.1 ModelTarget

A `ModelTarget` represents one approved physical reasoning target.

Required fields:

- `target_id` — stable JARVIS ID;
- `adapter_id` — registered invocation adapter;
- `provider_id` — logical provider family;
- `model_id` — provider/local model identifier;
- `endpoint_ref` — optional non-secret endpoint/config reference;
- `locality` — e.g. `local`, `private_remote`, `cloud`;
- `capabilities` — registered capability keys;
- `roles` — approved routing-role/profile keys;
- `max_context_tokens`;
- `supports_structured_output`;
- `supports_tools`;
- `supports_streaming` where relevant;
- `credential_ref` — name/handle only, never plaintext;
- `cost_profile` — versioned estimate metadata;
- `latency_class`;
- `enabled`;
- `benchmark_status`;
- `registry_version`.

Initial target records may represent the current Gemini and OpenAI work-reasoning models.

The schema must not assume all targets are cloud-hosted or OpenAI-compatible.

### 5.2 RoutingRequest

A `RoutingRequest` is the bounded deterministic input to routing.

Required fields:

- `routing_request_id`;
- `work_id`;
- optional `change_id`;
- optional `stage_key`;
- `task_kind`;
- `strategy_key`;
- `strategy_version`;
- `required_capabilities`;
- `privacy_class`;
- `locality_requirement`;
- `estimated_context_tokens`;
- `evidence_size_class`;
- `recent_progress_signals`;
- `recent_failure_signals`;
- `latency_preference`;
- `cost_preference`;
- `affinity_key` where continuity matters;
- bounded `routing_features`.

The initial router should operate primarily on canonical metadata and WorkStep summaries. Raw prompts/source documents are not required for deterministic stage routing and should not be copied into routing persistence.

### 5.3 EligibilitySnapshot

The eligibility layer produces an immutable decision snapshot containing:

- candidate target IDs considered;
- excluded target IDs;
- exclusion reason codes;
- target health snapshot/version;
- capability requirements;
- locality/privacy decision;
- credential-availability booleans;
- policy version/digest.

Eligibility is deterministic.

Typical exclusion reasons:

- `target_disabled`
- `capability_missing`
- `context_too_small`
- `locality_mismatch`
- `privacy_mismatch`
- `credential_unavailable`
- `target_unhealthy`
- `target_cooldown`
- `benchmark_not_accepted`
- `adapter_unavailable`

If no eligible target remains, the router does not silently relax constraints. The WorkItem enters an appropriate waiting/failure state.

### 5.4 RoutingDecision

A `RoutingDecision` records:

- `decision_id`;
- `routing_request_id`;
- `strategy_key/version`;
- `strategy_digest`;
- ordered eligible target IDs;
- selected target ID;
- decision reason codes;
- selected route/profile;
- fallback budget;
- created timestamp.

The stable result is an ordered candidate set, not an assumption that routing will always be binary strong/weak.

### 5.5 RoutingAttempt

Every model invocation attempt records bounded operational provenance:

- `attempt_id`;
- `decision_id`;
- `work_id`;
- target ID;
- attempt ordinal;
- start/end timestamps;
- latency;
- provider failure classification, if any;
- token/usage metadata when available;
- estimated cost metadata;
- whether it was primary or fallback;
- response-contract result;
- correlation/idempotency key where supported.

Do not store raw secret values or copy entire sensitive prompts into routing telemetry.

### 5.6 RoutingOutcome

A later completion/verification stage may attach:

- WorkStep success/failure;
- independent verifier result;
- accepted task result;
- final target/fallback path;
- total attempts;
- total latency;
- aggregate usage/cost estimate;
- outcome evidence reference.

The router itself does not decide whether the engineering result is correct.

## 6. Registries and extension model

### 6.1 ModelTargetRegistry

The registry is JARVIS-owned and versioned.

Initial target definitions should be explicit and small.

Runtime target availability may be machine-specific, but the canonical schema and role/capability definitions remain version-controlled.

The registry must support future adapters such as:

- current OpenAI SDK;
- current Gemini SDK;
- local OpenAI-compatible endpoint;
- future native local runtime;
- future specialist provider adapter.

Unknown adapter IDs fail closed.

### 6.2 ModelAdapterRegistry

`ModelAdapter` owns provider-specific invocation only.

Conceptual interface:

```python
class ModelAdapter(Protocol):
    adapter_id: str

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> BaseModel: ...
```

Adapters do not choose targets and do not own fallback.

Phase 4 should reuse or wrap the existing OpenAI/Gemini structured-output clients rather than duplicate SDK behavior.

### 6.3 RoutingStrategyRegistry

Routing algorithms are registered/versioned contracts.

Conceptual interface:

```python
class RoutingStrategy(Protocol):
    strategy_key: str
    strategy_version: int

    def rank(
        self,
        *,
        request: RoutingRequest,
        eligible_targets: tuple[ModelTarget, ...],
        history: RoutingHistoryView,
    ) -> RoutingStrategyResult: ...
```

Unknown strategies fail closed.

Initial strategy:

`engineering_stage.v1`

Future additions may include specialist, learned, Jev-assisted or ensemble strategies without changing WorkItem/EngineeringChange.

## 7. Initial deterministic stage-routing strategy

The first strategy adapts Switchyard's stage/progress concept to canonical JARVIS WorkSteps.

### 7.1 Initial route profiles

The initial strategy uses two **roles**, not fixed models:

- `efficient`
- `capable`

A target may qualify for one or both roles.

These are initial strategy semantics, not permanent core-schema limits.

### 7.2 Capable escalation signals

Examples:

- repeated reasoning/provider-independent failure;
- multiple failed hypotheses;
- repeated invalid structured output;
- stalled progress across bounded reasoning cycles;
- unknown incident/diagnostic complexity;
- unresolved conflicting evidence;
- large/heterogeneous evidence requiring higher capability;
- explicit task kind requiring capable tier;
- previous efficient-target attempt failed for quality/contract reasons.

### 7.3 Efficient/de-escalation signals

Examples:

- settled architecture/plan;
- routine next-step selection;
- mechanical continuation;
- bounded evidence summarization after research is complete;
- deterministic follow-through after prior capable decision;
- successful recent progress without diagnostic uncertainty.

Provider-pressure signals do not mean the task itself is hard; they affect target health, not capability tier.

### 7.4 Strategy output

The strategy returns:

- preferred role/profile;
- ordered target IDs;
- reason codes;
- confidence only as diagnostic metadata;
- optional hold/affinity recommendation.

No confidence value changes Authority or verification.

## 8. Target health and cooldown

### 8.1 Health states

Recommended operational health:

- `UNKNOWN`
- `HEALTHY`
- `DEGRADED`
- `COOLDOWN`
- `UNAVAILABLE`
- `DISABLED`

Health is scoped to a `ModelTarget`, not globally to all models of a provider.

### 8.2 Retry/fallback classes

Provider failures should be normalized through existing provider-resilience classification and mapped to routing action.

**Transient availability failures**, such as:

- rate limit;
- quota pressure where another approved target is available;
- 503/service unavailable;
- timeout;
- connection loss;

may mark the target degraded/cooldown and consume bounded fallback budget.

**Configuration/target failures**, such as:

- bad credentials;
- missing model;
- incompatible structured-output support;

may mark the target unavailable until configuration changes. Another already-approved eligible target may be used if routing policy permits.

**Policy/safety/content rejection** must not trigger provider hopping merely to obtain a different policy outcome. Fail closed or surface the restriction through the appropriate existing owner/application path.

### 8.3 Bounded fallback

Fallback must have a configured maximum hop/attempt budget.

The router cannot recursively retry forever or create cost explosions.

When the fallback budget is exhausted:

- preserve canonical WorkItem identity;
- transition to a truthful waiting/failure state;
- surface the blocker through existing WorkDelivery/status mechanisms;
- retain routing attempts as evidence.

### 8.4 Cooldown recovery

Cooldown is time-bounded and target-specific.

After expiry, the target may become eligible again according to policy.

Sustained provider pressure must eventually create an owner-visible blocker/escalation rather than silently retry forever.

## 9. Privacy and locality

Routing must support hard locality classes from the beginning.

Examples:

- `ANY_APPROVED`
- `PRIVATE_ONLY`
- `LOCAL_ONLY`

A cloud routing strategy cannot override `LOCAL_ONLY`.

A future SecretBroker may provide a handle indicating an approved secret exists, but the route layer never needs plaintext secret material.

Routing telemetry stores classifications and references, not secret content.

## 10. Cost and latency

Cost/latency are optimization inputs only after hard eligibility and quality requirements.

### 10.1 Cost metadata

Pricing changes over time. Therefore cost profile metadata should include:

- pricing source/reference;
- effective timestamp/version;
- input/output price estimates or cost class;
- whether the value is exact, configured or estimated.

Router decisions must not pretend estimated prices are billing truth.

### 10.2 Quality floor first

Initial production policy:

1. hard eligibility;
2. required quality/role;
3. health;
4. then cost/latency ordering among suitable targets.

The cheapest target is not selected if it cannot satisfy the approved route profile.

## 11. Affinity and safe switching

Some reasoning flows may depend on provider/model-specific conversational or tool state.

Phase 4 therefore supports an `affinity_key` and safe-switch boundaries.

Initial WorkReasoner integration is structured and stateless enough to switch between bounded reasoning cycles. If a future adapter introduces provider-resident state, the adapter/strategy must declare whether switching is safe.

Routing must never silently switch in the middle of an opaque provider-owned stateful transaction.

## 12. Persistence

Routing operational truth should reuse the existing WorkStore/engineering SQLite boundary rather than create a new database.

Recommended additive tables:

- `model_routing_decisions`
- `model_routing_attempts`
- `model_target_health`
- optional `model_routing_outcomes`

Properties:

- foreign-key/canonical link to WorkItem where applicable;
- positive versions/CAS for mutable health;
- append-only route decisions/attempts;
- payload protection through existing WorkPayloadCodec where sensitive metadata may exist;
- schema version/checksum discipline;
- no plaintext credentials.

Routing strategy and target-registry digests are persisted with each decision so a later reviewer can reconstruct why a target was selected.

## 13. DBOS and idempotency

DBOS remains the durable execution backend.

Routing happens inside the existing bounded WorkItem reasoning cycle.

Requirements:

- retries preserve the same WorkItem identity;
- route decision creation is idempotent for one canonical reasoning cycle;
- a fallback creates another `RoutingAttempt`, not another WorkItem;
- target-health mutation uses CAS/transactional persistence;
- DBOS recovery must not duplicate route records for the same deterministic attempt key.

External model APIs cannot universally guarantee exactly-once billing/invocation. Phase 4 must therefore provide deterministic correlation/idempotency identifiers where adapters support them and bounded duplicate protection, without falsely claiming exactly-once remote execution.

## 14. WorkReasoner integration

Current:

```text
WorkEngine
  -> BrainCoordinator
      -> ProviderWorkReasoner(provider=config.ai_provider)
          -> one configured provider/model
```

Phase 4 target:

```text
WorkEngine
  -> BrainCoordinator
      -> RoutedWorkReasoner
          -> RoutingRequest
          -> EligibilityPolicy
          -> RoutingStrategy
          -> ModelRouter
          -> ModelAdapter(selected target)
          -> structured BrainDecision
```

The existing `BrainDecision` contract remains unchanged where possible.

Interactive voice priority through `InteractiveBrainGate` remains unchanged.

Research actions continue to use `CurrentResearchService/Exa`; routing selects only the reasoning target that decides/synthesizes around those actions.

## 15. EngineeringChange integration

EngineeringChange does not delegate lifecycle authority to the router.

A change may own research, diagnostic, development or evaluation WorkItems. Each WorkItem may use the router for bounded reasoning.

Routing provenance links back to:

- `change_id`;
- `work_id`;
- stage/attempt;
- routing decision/attempt.

Architecture, acceptance and promotion gates remain independent and mandatory.

## 16. EngineeringKnowledge integration

Phase 4 runtime telemetry is not automatically accepted EngineeringKnowledge.

Later Phase 10/13 may project independently verified routing outcomes into `EVALUATION` knowledge.

The future flow is:

```text
routing telemetry
-> independent task verification
-> evaluation candidate
-> EngineeringKnowledge admission/lifecycle
-> accepted evaluation knowledge
-> reviewed routing policy/strategy update
```

This prevents self-reinforcing bad routes.

## 17. Evaluation architecture

A router is accepted only if it beats or justifies itself against fixed-model baselines.

Initial evaluation baselines:

- fixed current production target;
- always-capable target;
- always-efficient target;
- deterministic stage router.

Metrics:

- independently verified task success;
- structured-output validity;
- wrong-route/regret rate where measurable;
- unnecessary escalation rate;
- fallback success/failure;
- provider-pressure recovery;
- end-to-end task latency;
- model invocation latency;
- usage/tokens;
- estimated total model cost per completed task;
- number of model calls;
- route stability/churn;
- regression by task category.

Evaluation must report category-level results, not only one global score.

Phase 4 should use shadow/replay evaluation before allowing cost/quality history to influence production selection.

## 18. Initial production target pool

Phase 4 should begin with a deliberately small pool using already-supported provider adapters.

Exact model IDs remain configuration/registry data rather than architectural constants.

Initial requirements:

- at least one accepted capable target;
- at least one accepted alternative target where credentials/configuration permit;
- no target enabled merely because an SDK can call it;
- each target must pass structured-output and role fitness tests.

A local model target may be added later through the same registry after benchmark acceptance. No local-model installation is required to complete Phase 4.

## 19. Failure semantics

Fail closed for:

- unknown routing strategy/version;
- unknown adapter;
- no eligible target;
- violated locality/privacy constraint;
- corrupt registry/policy digest;
- unavailable required capability;
- ambiguous policy/content rejection;
- invalid persisted routing provenance.

Wait/retry/fallback only where the failure class explicitly permits it.

The router must produce truthful status reason codes suitable for WorkDelivery and status inspection.

## 20. Security review

The router is not an Authority surface.

Threats and controls:

- **provider hopping to bypass policy:** forbidden fallback class;
- **secret leakage through telemetry:** handles/classifications only;
- **cost amplification via loops:** bounded fallback/attempt budget;
- **malicious/unknown target registration:** versioned registry + explicit enablement + fail closed;
- **model self-selection:** eligibility and route policy remain JARVIS-owned;
- **poisoned outcome learning:** only independently verified/accepted outcomes may influence future adopted strategy;
- **local endpoint spoofing:** future adapter must use approved endpoint identity/provenance from Phase 5+ substrate;
- **router config drift:** version/digest persisted with each decision.

## 21. End-state extension points

The following must require **new adapters/strategies/config**, not a redesign:

- Jev decision backend;
- Switchyard native embedding if it later becomes advantageous;
- local llama.cpp/Ollama/vLLM-style target;
- coding specialist;
- diagnostic specialist;
- multimodal engineering model;
- learned router trained on accepted JARVIS outcomes;
- ensemble/advisor route;
- Phase-13 curriculum model evaluation;
- future provider gateway adapter.

## 22. Phase-4 acceptance criteria

Phase 4 is not complete until all required gates below pass.

### Core contracts

- same request/policy snapshot yields deterministic eligibility;
- unknown target/adapter/strategy fails closed;
- privacy/locality constraints cannot be relaxed by strategy;
- provider choice cannot affect Authority;
- routing records contain strategy/registry/policy provenance and no plaintext secret.

### Routing behavior

- routine WorkItem reasoning can select an efficient approved target;
- diagnostic/error/stall evidence can select/escalate to capable target;
- provider-pressure on the selected target can cool down that target and use another eligible target;
- policy/content rejection does not cross-provider fallback;
- fallback budget exhaustion surfaces a truthful blocker;
- one fallback chain preserves the same WorkItem/EngineeringChange identity.

### Recovery

- DBOS/runtime restart resumes the same WorkItem and routing attempt lineage;
- no duplicate WorkItem is created because a model target failed;
- routing persistence remains coherent across restart.

### Evaluation

- fixed-model baselines exist;
- stage-routing evaluation reports quality/cost/latency by task category;
- no learned/history-driven production selection is enabled without benchmark evidence.

### Owner-machine

A live bounded background engineering case must demonstrate:

- at least one real routed reasoning decision;
- visible route provenance;
- one controlled provider-pressure/fallback or equivalent target-health test where practical;
- same canonical WorkItem identity;
- no Authority/security regression;
- no new paid routing service or proxy required.

## 23. Architectural disposition

This architecture is intended to remain stable through the known autonomous-engineering roadmap.

Later phases should extend:

- target registry;
- adapter registry;
- routing strategies;
- evaluation knowledge;
- target-health policy;
- local/specialist models.

They should not need to replace:

- WorkItem;
- WorkStep;
- EngineeringChange;
- EngineeringKnowledge;
- Authority;
- approval/verification;
- routing request/decision/attempt provenance.

That is the Phase-4 compatibility contract.
