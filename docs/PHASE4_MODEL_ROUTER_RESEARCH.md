# Phase 4 Research — Research + Diagnostic Model Router

Status: **RESEARCH COMPLETE / ARCHITECTURE INPUT FROZEN 2026-09-25**

This document records the technology research and architectural conclusions for Phase 4 of the governed autonomous-engineering program.

Phase 4 must create one provider/model-neutral routing boundary for research, diagnostics and engineering reasoning. It is not a provider-failover patch for Gemini/OpenAI; it is the routing substrate that later phases will reuse for unknown-incident investigation, capability acquisition, specialist-model evaluation, local models, benchmarking and governed self-evolution.

## 1. End-state fit

The accepted north-star requires a stable governed engineering core that can support repair, unknown investigation, owner-requested capability acquisition and future process families without duplicating Authority, EngineeringKnowledge, WorkItems, verification, promotion or provenance.

Phase 4 therefore has to satisfy two time horizons simultaneously:

- **Now:** route background engineering reasoning across the currently approved OpenAI/Gemini targets, respond safely to provider pressure and reduce unnecessary use of expensive models.
- **Later:** admit local models, coding/diagnostic specialists, future routing strategies, learned selectors and optional decision technologies without replacing the canonical routing contracts.

The expected future change should be **adding targets, adapters, strategies and evaluators**, not redesigning WorkItem, EngineeringChange, Authority or routing provenance.

No architecture can guarantee that future requirements will never require revision. The Phase-4 goal is instead to make all known Phase 5–14 needs additive behind stable interfaces.

## 2. Existing JARVIS constraints

Protected-main already provides the important primitives Phase 4 must reuse:

- canonical durable `WorkItem`, `WorkStep` and `WorkDelivery`;
- DBOS-backed durable execution;
- `EngineeringChange` as the multi-stage engineering aggregate;
- `EngineeringKnowledge` for advisory verified knowledge and later evaluation history;
- deterministic Authority and strong owner approval boundaries;
- provider-neutral current research with Exa retrieval separated from synthesis;
- provider failure classification;
- existing OpenAI/Gemini structured-output clients;
- interactive voice priority over background model reasoning;
- isolated development, CI and protected-main governance.

Phase 4 must not create a second task system, second approval system, second research store, second deployment system or an unrestricted model gateway.

Realtime voice/conversation routing is explicitly out of the initial Phase-4 production scope. The contracts must be reusable there later, but the first consumer is background engineering reasoning.

## 3. Technology research

### 3.1 NVIDIA NeMo Switchyard

Research source:

- https://github.com/NVIDIA-NeMo/Switchyard
- https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/routing_algorithms/stage_router_routing.md
- https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/routing_algorithms/overview.md
- https://github.com/NVIDIA-NeMo/Switchyard/blob/main/INSTALLATION.md

Useful ideas:

- separate **efficient** and **capable** model roles rather than hard-coding model identities;
- stage-aware routing from tool results and agent progress;
- escalate for exploration, errors, repeated failure or hard reasoning;
- de-escalate to efficient models for routine/mechanical execution;
- retain per-session routing state;
- allow task, execution, composite, advisor and future custom policies;
- provider-neutral request/response protocol separation.

JARVIS disposition:

**ADAPT THE ALGORITHM AND ROLE MODEL; DO NOT MAKE SWITCHYARD THE PRODUCTION ROUTER DEPENDENCY IN PHASE 4.**

Why:

- JARVIS already owns richer canonical WorkStep truth than Switchyard has to infer from generic chat/tool traffic.
- JARVIS must keep Authority, privacy, target health and provenance rules in its own deterministic boundary.
- Switchyard's project/API is still evolving, and some routing examples require unreleased/source-build features.
- Embedding a third-party routing runtime would make provider/model selection an external subsystem when JARVIS already has the canonical orchestration state needed to route directly.

The architecture therefore makes Switchyard-style stage routing one replaceable `RoutingStrategy`, not the core contract.

### 3.2 vLLM Semantic Router

Research source:

- https://github.com/vllm-project/semantic-router
- https://github.com/vllm-project/semantic-router/blob/main/website/docs/overview/semantic-router-overview.md
- https://github.com/vllm-project/semantic-router/blob/main/website/docs/installation/installation.md

Useful ideas:

- separate **Signals -> Projections -> Decisions -> Algorithms -> Provider Models**;
- keep routing policy independent from the physical model pool;
- make privacy/location/system-state signals first-class;
- support multiple routing algorithms behind stable entrypoints;
- separate route decision from backend serving;
- evaluate and replay routing outcomes;
- learned selectors should come only after representative workload data exists.

JARVIS disposition:

**ADAPT THE ARCHITECTURAL SEPARATION; DO NOT DEPLOY THE FULL ENVOY/ROUTER STACK IN PHASE 4.**

Why:

- JARVIS is a single-owner Windows application, not a Kubernetes inference gateway.
- the maintained local serving stack expects Linux/macOS/WSL2 plus container infrastructure;
- adding Envoy/router/dashboard/operator infrastructure would be a large operational dependency for a decision that can be made in-process from canonical WorkItem state;
- JARVIS needs the conceptual separation, not a second control plane.

### 3.3 LiteLLM Router

Research source:

- https://docs.litellm.ai/docs/routing

Useful ideas:

- per-deployment health rather than all-or-nothing provider health;
- cooldown after 429s or repeated failures;
- bounded retry/fallback chains;
- exclude the failed target while keeping healthy peers eligible;
- latency/cost/TPM/RPM-aware selection;
- error-type-specific retry policies;
- do not treat content-policy rejection like ordinary retryable provider pressure.

JARVIS disposition:

**ADAPT THE TARGET-HEALTH, COOLDOWN AND BOUNDED-FALLBACK PATTERNS; DO NOT INSERT LITELLM PROXY/ROUTER INTO THE PRODUCTION PATH IN PHASE 4.**

Why:

- JARVIS already owns OpenAI/Gemini SDK boundaries, provider failure classification and credentials;
- an additional gateway would duplicate provider abstraction and widen the dependency/runtime surface;
- Phase 4 only needs a small approved target pool, so an in-process router is simpler and easier to govern;
- LiteLLM remains a possible future adapter if provider count or deployment complexity grows enough to justify it.

### 3.4 LLMRouterBench

Research source:

- https://arxiv.org/abs/2601.07206
- https://aclanthology.org/2026.findings-acl.1881/
- https://github.com/pzq-xjtu/LLMRouterBench

Research findings relevant to JARVIS:

- 400K+ benchmark instances across 21 datasets and 33 models;
- unified evaluation of performance-only and performance-cost routing;
- many routing methods perform similarly under unified evaluation;
- several sophisticated/commercial routers do not reliably beat a simple baseline;
- larger model pools show diminishing returns;
- careful model curation matters;
- latency-aware evaluation is necessary in addition to quality/cost.

JARVIS disposition:

**ADAPT THE EVALUATION DISCIPLINE.**

Phase 4 must not assume that a more complex router is automatically better. Every routing strategy must be compared against fixed-model baselines on JARVIS-specific engineering cases.

### 3.5 RouteLLM

Research source:

- https://github.com/lm-sys/RouteLLM
- https://github.com/lm-sys/RouteLLM/blob/main/pyproject.toml

Useful ideas:

- strong-vs-weak model routing;
- routing-threshold evaluation;
- cost/performance benchmark framing.

JARVIS disposition:

**REFERENCE ONLY; DO NOT INSTALL IN THE CURRENT PRODUCTION ENVIRONMENT.**

The current package brings Torch/Transformers/Datasets/LiteLLM and pins `numpy<2`, while JARVIS intentionally uses NumPy 2.x. The conceptual strong/weak baseline is useful; the dependency is not.

### 3.6 Managed routers and gateways

Reviewed patterns include managed/commercial gateways and cloud model routers such as OpenRouter, Portkey, Azure model routing and Bedrock prompt routing.

JARVIS disposition:

**NOT THE CANONICAL ROUTER.**

They may later become provider adapters or optional deployment paths, but routing policy and provenance must remain JARVIS-owned. JARVIS must not require a third-party router subscription or cloud control plane in order to choose its engineering model.

### 3.7 Jev

Jev was separately considered as a low-cost decision-model technology.

Owner decision for this phase:

**DEFERRED. DO NOT IMPLEMENT JEV IN PHASE 4.**

The Phase-4 interfaces must allow a future Jev-backed `RoutingStrategy`/decision backend to be benchmarked without changing the rest of the architecture. Jev adoption will be a later optimization task with explicit before/after cost, quality and latency measurement.

## 4. Research conclusions

### 4.1 No single external framework should own Phase 4

The strongest design is a JARVIS-owned routing core that adapts proven ideas:

- **vLLM Semantic Router:** signals/decisions/algorithm/target separation;
- **Switchyard:** stage/progress-aware efficient-vs-capable routing;
- **LiteLLM:** target-scoped health, cooldown and bounded fallback;
- **LLMRouterBench:** baseline-driven evaluation and cost/quality/latency measurement.

This gives JARVIS mature patterns without importing an unnecessary gateway/control plane.

### 4.2 Initial routing must be deterministic

Phase 4 starts with deterministic eligibility and deterministic routing policy.

A learned router is not allowed to become production truth until representative JARVIS-specific outcome data exists and independent evaluation demonstrates a measurable benefit over the baseline.

### 4.3 The target pool must be small and curated

More models are not automatically better. Initial production routing should use only owner-approved, benchmarked targets with explicit capability metadata.

Local or specialist models enter the pool only after JARVIS-specific evaluation demonstrates fitness for their declared role.

### 4.4 Search and reasoning remain separate

Exa remains a retrieval/evidence provider. The model router chooses the reasoning target that consumes bounded research evidence.

Search-provider health does not become model-routing truth, and model provider choice does not change evidence sufficiency rules.

### 4.5 Provider/model choice never changes Authority

The router may choose who reasons. It may not choose what is authorized.

Changing Gemini -> OpenAI -> local must not alter:

- action risk;
- permissions;
- strong owner approval;
- architecture gates;
- acceptance gates;
- secret access;
- sandbox policy;
- protected-main rules;
- verification requirements.

### 4.6 The stable abstraction is target + strategy, not provider name

The core architecture must not assume exactly two providers or exactly two model tiers.

An initial stage strategy may choose between `efficient` and `capable`, but the stable result is an ordered candidate set of registered `ModelTarget` records. Future specialist/local/ensemble strategies can be added without changing WorkItem or EngineeringChange.

## 5. End-state compatibility review

The architecture was explicitly checked against Phases 5–14.

- **Phase 5 Secure Engineering Substrate:** routing can enforce locality/secret-handle/capability constraints without taking ownership of SecretBroker or DependencyBroker.
- **Phase 6 Unknown-Incident Investigation:** diagnostic WorkItems can use specialist or capable models while retaining the same EngineeringChange and verification boundaries.
- **Phase 7 Promotion/Verification:** routing provenance is evidence only; it cannot approve or promote.
- **Phase 8 Capability Registry:** capability packages may declare model/inference requirements without creating a second model registry.
- **Phase 9 Owner-Requested Capability Acquisition:** research, architecture and development reasoning can route independently while remaining one EngineeringChange.
- **Phase 10 Closed-Loop Learning:** verified routing outcomes can be projected into EngineeringKnowledge/EVALUATION without making runtime telemetry automatically trusted knowledge.
- **Phase 11 Gap Detection:** recurring fallback/cost/latency patterns may become evidence for an ImprovementCandidate, not automatic mutation.
- **Phase 12 Shadow Improvement:** alternative routing strategies can run in shadow and compare against the accepted baseline.
- **Phase 13 Specialist Model Evaluation:** new local/cloud specialist models register as targets and are benchmarked without router redesign.
- **Phase 14 Governed Self-Evolution:** JARVIS can improve target pools or strategy versions through the existing architecture/acceptance/promotion lifecycle.

Conclusion: **no foundational redesign is expected for the known end-state roadmap.** Future work should be additive: new adapters, targets, strategies, evaluators and learned decision backends.

## 6. Permanent Phase-4 research decisions

1. JARVIS owns routing policy and provenance.
2. Initial production consumer is background engineering reasoning.
3. Realtime conversation routing remains outside initial Phase 4.
4. Initial strategy is deterministic and WorkStep-aware.
5. Provider/model target health is target-scoped.
6. Fallback is bounded and error-class aware.
7. Policy/content rejection never triggers cross-provider fallback merely to evade the rejection.
8. Routing uses metadata/minimized features; secrets do not become routing telemetry.
9. Outcome quality comes from independent verification, not router/model confidence.
10. Learned routing and Jev are deferred until JARVIS-specific evaluation proves value.
11. No new mandatory paid router, proxy, server or control plane is introduced.
12. The architecture must support local and specialist models through adapters without changing canonical WorkItem/EngineeringChange contracts.
