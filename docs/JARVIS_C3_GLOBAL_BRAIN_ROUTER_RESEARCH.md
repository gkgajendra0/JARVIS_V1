# C3 Deep Research — Global Brain Router v1

Status: **RESEARCH COMPLETE / ARCHITECTURE RECOMMENDED / IMPLEMENTATION NOT STARTED**

Date: 2026-09-29

Parent plan: `JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md`

## 1. Research question

How should JARVIS evolve the existing Phase-4 model router into a global cost-aware intelligence-routing pipeline without:

- creating a competing second model router;
- weakening owner Authority or action admission;
- confusing deterministic capability execution with model selection;
- duplicating retry/fallback/cost logic;
- adding an unnecessary external gateway or service;
- degrading realtime voice UX;
- locking JARVIS to one provider or model runtime?

The target C3 order remains:

1. deterministic / exact known decision;
2. bounded decision layer when later admitted;
3. local model when later admitted;
4. cheap cloud;
5. standard / strong cloud;
6. owner/blocker when no approved route exists.

C3 establishes the routing architecture. C4/C5/C7 populate later tiers with benchmark evidence.

## 2. Current JARVIS substrate

Fresh repository inspection confirms Phase 4 already contains most of the hard model-routing machinery:

- immutable `RoutingRequest` facts;
- `ModelTarget` registry with locality, capabilities, roles, context limits, benchmark status and optional CostProfile;
- deterministic eligibility policy;
- privacy/locality constraints;
- credential availability;
- target health and cooldown;
- versioned strategies and strategy digests;
- durable routing decision reuse across DBOS retries;
- bounded fallback;
- provider-neutral invocation adapters;
- per-attempt provider/model/usage/latency/cost telemetry from C1;
- mission aggregation and non-token provider cost events.

`ModelLocality.LOCAL` already exists, so C5 does not require another router to introduce local models.

The current limitation is scope: the router selects a **model target** only after a background Work reasoning cycle has already decided that model reasoning is necessary.

## 3. Most important C3 finding

C3 must route **decision-making paths**, not directly execute arbitrary capabilities.

A deterministic route means:

> Canonical JARVIS state proves the next approved BrainDecision without generative reasoning.

It does **not** mean:

> The router directly performs the action.

Execution remains in the existing governed Work/Hands/capability runtime. Existing action admission, Authority, completion guards, sandboxing, verification and promotion remain downstream and unchanged.

This distinction is critical. Routing can reduce intelligence cost; it cannot grant authority.

## 4. Where the largest immediate savings are

The Work engine currently asks the LLM to select the next bounded action for every reasoning cycle, even when the next action can sometimes be proven mechanically from canonical WorkStep state.

Safe initial deterministic examples include:

- development work with no prepared workspace and `dev_prepare_workspace` allowed -> prepare workspace;
- diagnostics with no canonical incident inspection and `diag_get_incident` allowed -> inspect incident;
- after a passing development test with no later diff and `dev_diff` allowed -> inspect diff.

These are good C3 candidates because:

- the action is already explicitly allowed;
- required parameters are empty or deterministically derivable;
- existing guards already require the state transition;
- no model interpretation is required;
- model invocation can be skipped completely.

Rules that need semantic interpretation, generated source, hypothesis formation, architecture judgment, research-query formulation or ambiguous parameters must **abstain** and fall through to the model path.

## 5. External technology research

### 5.1 vLLM Semantic Router

Current vLLM Semantic Router is the closest architectural reference.

Useful concepts:

- separate request **signals** from policy;
- policy determines the eligible/candidate set;
- a selection algorithm chooses only inside the allowed set;
- local, specialist and cloud paths can coexist;
- routing decisions are observable/replayable;
- tool execution and application state remain outside the router.

Its current project documentation explicitly separates semantic routing from the AI gateway and inference router, and its agent recipe states that the client remains responsible for executing tools and managing application state.

Why JARVIS should **not adopt it as the C3 runtime**:

- it is primarily an inference/model-routing service;
- local quickstart assumes Linux/macOS/WSL2 plus Docker;
- richer deployment commonly adds Envoy / gateway infrastructure;
- it does not replace JARVIS Authority, Work state, capability runtime or EngineeringChange governance;
- JARVIS already has equivalent hard routing primitives integrated with its durable state.

Decision: **adopt the architecture pattern, not the dependency** for C3.

Sources:
- https://github.com/vllm-project/semantic-router/blob/main/website/docs/overview/semantic-router-overview.md
- https://github.com/vllm-project/semantic-router/blob/main/website/docs/intro.md
- https://github.com/vllm-project/semantic-router/blob/main/config/recipes/agent/README.md
- https://github.com/vllm-project/semantic-router/blob/main/website/docs/installation/installation.md

### 5.2 LiteLLM

LiteLLM is strong at:

- unified provider transport;
- retries/fallbacks;
- deployment health/cooldown;
- cost-based/latency routing;
- local backends such as Ollama;
- gateway budgets and spend tracking.

Why it should **not replace C3**:

- it chooses among LLM deployments/models, not whether JARVIS needs AI at all;
- it does not own JARVIS capability/action Authority;
- JARVIS already has bounded retries, health, fallback, cost provenance and provider adapters;
- putting two autonomous retry/fallback routers in series risks duplicated or multiplicative upstream calls.

Potential later role: optional **transport/provider gateway below JARVIS routing**, especially if provider count grows. If adopted later, exactly one layer must own retry/fallback semantics.

Sources:
- https://docs.litellm.ai/docs/
- https://docs.litellm.ai/docs/routing
- https://docs.litellm.ai/docs/proxy/users

### 5.3 Aurelio Semantic Router

Aurelio Semantic Router uses semantic-vector similarity for very fast routing and can run with local encoders.

Good later candidate for:

- bounded intent classification;
- known-command detection;
- simple route classification;
- a C4 benchmark against Jev and deterministic rules.

Not appropriate for:

- authorization;
- hard privacy/locality policy;
- verification truth;
- arbitrary next-action selection.

Decision: **C4 candidate, not C3 core**.

Source:
- https://github.com/aurelio-labs/semantic-router

### 5.4 RouteLLM / FrugalGPT / learned routers

Research consistently supports cascades: send easy work to cheaper models and escalate uncertain/low-quality work.

RouteLLM learns strong-vs-weak routing from preference data. FrugalGPT demonstrated that cascades can substantially reduce spend while preserving quality. More recent work continues to use route-then-escalate designs.

This validates the later JARVIS direction but these systems operate primarily on model selection, not deterministic capability routing or owner Authority.

Decision: use their evaluation principles in C7 after JARVIS has task-specific benchmark/mission data.

Sources:
- https://arxiv.org/abs/2406.18665
- https://arxiv.org/abs/2305.05176
- https://arxiv.org/abs/2606.27457

### 5.5 Not Diamond

Not Diamond provides hosted learned model routing with quality/cost/latency tradeoffs and custom routers. Its current pricing documentation says the router itself adds roughly 100–150 ms average latency and is a paid external service.

For JARVIS, making the cost-control core depend on another paid cloud decision service before local/deterministic routing is proven would be counterproductive.

Decision: **do not make it a C3 dependency**. It may be useful only as a future benchmark comparator.

Sources:
- https://docs.notdiamond.ai/docs/what-is-model-routing
- https://www.notdiamond.ai/pricing

## 6. Recommended C3 architecture

C3 should evolve the existing `jarvis.model_routing` package into **one logical routing pipeline with two stages**, not introduce a competing model router.

### Stage A — intelligence-path policy

Input: a subsystem-neutral, typed routing-facts contract.

Possible result:

- `deterministic`;
- `bounded_decision` (reserved/disabled until C4);
- `model`;
- `blocked` when no approved route exists.

Stage A does not invoke a model and does not execute tools.

### Stage B — model-target selection

Only when Stage A selects `model`:

- project the global facts into the existing `RoutingRequest`;
- run current target eligibility;
- run versioned strategy;
- select from approved local/cloud ModelTargets;
- use current durable fallback, health and invocation path.

Therefore C3 **reuses** ModelRouter rather than replacing it.

Conceptually:

```
Subsystem request / canonical state
        |
        v
Typed Brain Routing Facts
        |
        v
Hard policy / deterministic resolver registry
        |
        +--> exact deterministic BrainDecision
        |       |
        |       v
        |   existing governed executor
        |
        +--> abstain
                |
                v
        bounded-decision slot (C4; disabled in C3)
                |
                v
        existing ModelRouter
          eligibility
          strategy
          health
          fallback
                |
                v
      local / cheap / standard / strong target
                |
                v
        existing model invoker
```

## 7. Global request facts

Do not turn `routing_features` into an untyped dumping ground.

C3 should introduce a small typed global contract containing at least:

- stable route request ID;
- mission/scope ID;
- subsystem key;
- task kind;
- required capabilities;
- privacy class;
- locality requirement;
- latency preference/class;
- cost preference;
- estimated context size;
- evidence/knowledge state;
- required output contract;
- quality/escalation class;
- bounded recent progress/failure facts;
- optional affinity/session key.

Hard policy facts must come from trusted JARVIS state, configuration and verified runtime observations. User prompt text, model output and classifier confidence must never expand Authority.

## 8. Deterministic resolver contract

Recommended resolver behavior:

```
resolve(context) -> MATCH(BrainDecision, reason_codes)
                  | ABSTAIN(reason_code)
```

Rules:

- resolver must be explicitly registered/versioned;
- resolver may only select an action present in `allowed_actions`;
- resolver parameters must be empty or deterministically derived from trusted state;
- ambiguity => ABSTAIN;
- unsupported state => ABSTAIN;
- resolver failure must not widen permissions;
- existing BrainCoordinator action validation remains mandatory;
- existing completion/admission/verification guards remain mandatory.

C3 should start with only a few high-confidence rules. More rules should be admitted from measured evidence, not convenience.

## 9. Provenance requirement

C3 needs route provenance even when **no model call happens**.

Without this, the final TV experiment can show model spend but cannot prove how many paid calls the router avoided.

Add a lightweight durable brain-route event/decision record in the existing canonical WorkStore/routing substrate containing only bounded metadata:

- route request ID;
- work/mission scope;
- subsystem/task kind;
- route kind;
- deterministic resolver ID/version when applicable;
- reason codes;
- linked ModelRouter decision ID when a model route is used;
- selected target ID when applicable;
- timestamp;
- strategy/policy version/digest.

Do **not** persist raw prompts, model hidden reasoning, credentials or sensitive tool arguments.

This is provenance, not a second router.

## 10. C3 rollout mode

Recommended rollout:

1. **shadow mode**
   - compute deterministic proposal;
   - still use current model path;
   - compare deterministic proposal to accepted model/action outcome;
   - collect mismatch reasons.

2. **apply mode for accepted rules**
   - bypass the model only for deterministic rules with passing replay/acceptance evidence;
   - every other request abstains to the existing model path.

3. keep a simple rollback switch to return immediately to the current Phase-4 behavior.

This follows the same evidence-first principle used by current production routing systems: hard policy first, experiments admitted only after replay/evaluation.

## 11. What C3 should NOT implement yet

Defer deliberately:

- Jev integration -> C4;
- semantic-router classifier integration -> C4 candidate;
- actual local LLM target -> C5;
- local-model task admission -> C5;
- context compression/retrieval changes -> C6;
- real cheap/standard/strong price-based ordering -> C7;
- broad Hands/memory/voice adoption -> C8;
- budget governor -> C11;
- LiteLLM/vLLM gateway deployment -> only if later evidence justifies it.

C3 should create the stable seams these later slices plug into.

## 12. Recommended C3 implementation sequence

### C3.1 — typed global route contracts

Add:

- route-kind enum;
- subsystem/task/quality/output facts;
- versioned global route policy contract;
- deterministic resolver protocol/registry;
- global route provenance record.

No behavior change yet.

### C3.2 — Work adapter

Project `BrainRequest` + canonical WorkStep state into the global facts contract.

Reuse the existing model `RoutingRequest` builder for Stage B initially.

### C3.3 — deterministic shadow rules

Implement a very small rule set:

- development initial workspace preparation;
- diagnostics initial incident inspection;
- development post-test diff inspection when state proves it is required.

Record proposal and compare against existing model decisions.

### C3.4 — apply accepted deterministic rules

After deterministic replay tests show no semantic mismatch:

- enable bypass for accepted rules;
- prove `ModelInvoker` is not called;
- record route provenance;
- confirm cost report shows zero model attempt for that decision cycle.

### C3.5 — generic/non-engineering contract proof

Add a test fixture for a non-engineering subsystem (for example memory) proving that the same global route facts/policy can admit and select an approved model target.

Do not move production memory/Hands/voice traffic yet; that remains C8.

## 13. C3 acceptance criteria

C3 is complete only when:

- all existing Phase-4 routing tests still pass;
- current background Work behavior remains available as rollback;
- at least one real Work cycle deterministically bypasses model invocation;
- deterministic bypass is persisted and measurable;
- ambiguous deterministic cases abstain cleanly;
- a deterministic resolver cannot choose an unapproved action;
- provider pressure still does not masquerade as task difficulty;
- privacy/locality/capability/benchmark eligibility remains hard policy;
- one non-engineering test path uses the same global contract;
- no Authority, EngineeringChange, sandbox, verification or promotion boundary is weakened;
- no realtime voice path is changed by C3;
- CI + Windows Phase-9 replay remain green.

## 14. Final TV capability experiment implications

The end-to-end TV-control experiment should eventually report **where the money went**, not merely whether the capability worked.

By C10 the report should include:

- total mission cost;
- model cost by stage/provider/model;
- Exa/search/content cost;
- bounded-decision-layer cost if C4 adopts one;
- deterministic route count;
- model calls avoided by deterministic rules;
- local-model call/share after C5;
- cheap/standard/strong cloud call/share after C7;
- input/output/cached/reasoning tokens;
- retries/fallbacks and their incremental cost;
- latency by stage;
- research, architecture, development, verification and external-acceptance cost;
- TTS reported separately from paid-brain spend;
- final physical TV-control result.

The first useful question after the experiment will therefore be answerable with evidence:

> Which stage and intelligence tier consumed the most money, and why?

That evidence will drive C11 Cost Governor limits instead of guessing budgets in advance.

## 15. Research conclusion

**Proceed with C3, but build it as a thin global path-policy layer around the existing Phase-4 ModelRouter.**

Do not replace Phase 4.
Do not install LiteLLM or vLLM Semantic Router as the C3 core.
Do not put deterministic capabilities into fake ModelTargets.
Do not let routing grant Authority.

Use external routers as design/benchmark references, keep JARVIS-native trusted state and governance, and make the first real savings come from deterministic Work decisions that currently waste an LLM call.
