# JARVIS Model Router + Codex Development Direction

Status: **OWNER DIRECTION RECORDED / RESEARCH-BACKED / NO NEW PRODUCTION ROUTING AUTHORIZED**

Date: 2026-10-04

Related:
- `JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md`
- `JARVIS_COST_OPTIMIZATION_DECISIONS.md`
- `JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md`
- `DEVELOPMENT_ENGINE_CONTROL_PLANE_ARCHITECTURE.md`
- `PHASE4_MODEL_ROUTER_ARCHITECTURE.md`

## 1. Why this decision exists

During C6 owner-machine acceptance, the owner challenged two assumptions:

1. JARVIS should not consume the strongest ChatGPT-plan model for routine reasoning/coding when a cheaper sufficient model can do the work.
2. JARVIS should not rebuild a complete coding agent if a supported ChatGPT-plan/Codex runtime can perform the coherent repository-development loop while JARVIS retains governance.

These are now durable architecture requirements. They must not be lost when the current C6/DevelopmentEngine work continues.

## 2. Permanent routing principle

JARVIS must choose the **cheapest sufficient intelligence path**, subject to correctness, safety, latency, privacy, owner Authority, current provider health and benchmark evidence.

The logical ladder remains:

1. deterministic / already-known capability;
2. bounded decision layer when admitted;
3. local model;
4. economical cloud model;
5. balanced/strong cloud model;
6. frontier model only when evidence justifies escalation;
7. owner/blocker when no approved route exists.

This is one logical Global Brain Router. Do not create a second competing router for development.

Current OpenAI model names are examples, not permanent architecture:

- Luna-class: focused/repetitive/low-cost cloud work;
- Terra-class where available: routine professional/code changes;
- Sol-class: normal substantial coding/research/reasoning;
- Astra-class: genuinely difficult or unfamiliar reasoning/coding.

The registry/benchmark layer, not hard-coded product names, must determine the actual target.

## 3. Astra is an escalation tier, not the default

Astra-class reasoning is reserved for cases such as:

- difficult unfamiliar failures;
- architecture changes with broad consequences;
- hard debugging after cheaper routes fail;
- security/safety-sensitive reasoning where stronger capability is justified;
- benchmark-proven tasks where lower tiers do not meet the quality contract.

Routine repository inspection, short edits, classification, bookkeeping, deterministic transitions and ordinary implementation should not automatically use Astra.

Escalation must be evidence-driven. A cheaper-model failure may justify trying a stronger model; task wording alone must not automatically select the most expensive tier.

## 4. Development should use a coding specialist, not normal Chat UI automation

The target development flow is:

```text
Owner goal
   |
   v
JARVIS control plane
   |
   | goal / architecture / authority / budget / evidence
   v
DevelopmentEngine
   |
   +--> Codex / approved coding specialist
   |       |
   |       +--> inspect repository through governed tools
   |       +--> edit isolated worktree
   |       +--> run tests
   |       +--> inspect failures
   |       +--> iterate
   |       +--> produce candidate commit/result
   |
   v
JARVIS verification / CI / promotion / activation / rollback
```

JARVIS remains the manager and source of canonical truth. The coding specialist supplies engineering intelligence only.

Do **not** build the architecture around browser/desktop automation of the normal ChatGPT chat UI. Sign in with ChatGPT does not grant an app access to the user's ChatGPT conversations, and direct Responses plan-sharing requests do not provide persistent ChatGPT conversation storage.

Use supported integration boundaries instead:
- Sign in with ChatGPT / ChatGPT-plan OAuth;
- Codex SDK/runtime or Codex app-server when appropriate;
- provider-neutral `DevelopmentEngine` contracts;
- JARVIS-governed repository/test/commit tools.

## 5. ChatGPT-plan usage is subscription-backed, not unlimited

Using Codex/Responses with ChatGPT-plan OAuth can avoid normal API-key per-token billing for included plan usage, but it must not be treated as unlimited capacity.

For Plus, the five-hour plan allowance is shared across participating apps. Work/Codex/model choice, context size, reasoning effort and multi-step tasks all affect how quickly allowance is consumed.

Therefore the router must consider:
- current allowance/quota health;
- model tier;
- context size;
- expected number of turns;
- mission importance;
- retry/escalation history;
- whether a local/deterministic result is sufficient.

Provider pressure is a resource condition, not evidence that the task itself needs a stronger model.

## 6. C6 remains necessary even with Codex

Codex does not make context optimization obsolete.

Large irrelevant context still:
- consumes shared allowance faster;
- increases latency;
- can inject stale/conflicting information;
- makes cheap models less practical.

C6 therefore remains upstream of cloud-model/coding-specialist routing:

```text
canonical JARVIS state
        |
        v
C6 bounded relevant context
        |
        v
Global Brain Router
        |
        +--> deterministic
        +--> bounded decision
        +--> local
        +--> economical cloud
        +--> Sol-class
        +--> Astra-class escalation
        +--> Codex DevelopmentEngine for coherent repository work
```

C6 must never remove information required for safe/correct decisions. If equivalence or task-specific quality is not proven, C6 stays SHADOW for that boundary or falls back to broader context.

## 7. Relationship between model routing and DevelopmentEngine

There are two separate choices:

### Choice A — does this work need a model at all?

Owned by the Global Brain Router:
- deterministic;
- bounded decision;
- local;
- cloud.

### Choice B — when this is coherent software-development work, which approved engineering runtime/model should execute the ticket?

Owned by DevelopmentEngine admission plus the same underlying routing/availability evidence.

DevelopmentEngine must not hardcode "Astra for coding".

The long-term direction is:
- routine engineering: cheapest benchmark-qualified model/runtime;
- normal substantial engineering: Sol-class or equivalent;
- very hard engineering: Astra-class escalation;
- local coding model: eligible when owner-machine benchmarks prove sufficient quality;
- provider/coding runtime: replaceable behind the provider-neutral interface.

## 8. Escalation contract

A lower tier may escalate only for explicit reasons, for example:
- failed verification;
- repeated incorrect patch;
- unresolved compiler/test failure;
- missing capability at current tier;
- confidence/quality gate below threshold;
- task enters a protected high-complexity class.

Escalation provenance must record:
- previous route;
- reason code;
- failure/evidence reference;
- new target tier;
- incremental usage/cost.

Do not silently jump to the strongest model.

## 9. What JARVIS must keep owning

Even if Codex performs most of the code-edit/test loop, it must not become the JARVIS control plane.

JARVIS keeps:
- owner goal and Authority;
- EngineeringChange/WorkItem state;
- approved architecture;
- research evidence/provenance;
- secrets;
- dependency admission;
- isolated worktree/tool permissions;
- sandbox/test policy;
- exact commit/result binding;
- CI;
- promotion;
- activation;
- rollback;
- external acceptance;
- cost/quota governance.

This is the reason to wrap an existing coding agent instead of delegating the entire autonomous lifecycle to it.

## 10. Current C6 acceptance evidence — 2026-10-04

The fixed C6 corpus currently has:

- development repair case: corrected legacy-vs-optimized pair **equivalent**;
- development final-commit case: legacy-vs-optimized pair **equivalent**;
- research re-resolution case: action and owner/safety fields match, but action parameters differ.

Therefore:
- C6 APPLY is **not yet admitted**;
- production stays SHADOW;
- do not weaken parameter equivalence merely to get a pass;
- diagnose whether the research mismatch is lost context, intentionally non-canonical free-form parameter generation, or a missing deterministic/canonical parameter-construction boundary.

The research case achieved large context reduction, but reduction is not accepted if it changes safety/verification semantics.

## 11. Next research before changing runtime routing

Before implementation of model-tier routing changes:

1. inventory which JARVIS paths currently pin a specific ChatGPT-plan model;
2. map each path to task/quality classes;
3. benchmark at least local/Luna-class/Sol-class/Astra-class candidates on JARVIS-specific fixtures;
4. measure quality, latency and allowance consumption;
5. define escalation reason codes;
6. decide how Codex DevelopmentEngine receives model selection without creating a second router;
7. validate Codex app-server/SDK integration against the existing provider-neutral adapter;
8. keep paid API fallback opt-in/bounded;
9. keep current production model behavior as rollback until owner-machine acceptance passes.

## 12. Official OpenAI references checked 2026-10-04

- Sign in with ChatGPT overview:
  https://developers.openai.com/siwc/token-sharing-open-source
- Accounts/sessions and shared Plus allowance:
  https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
- Codex app-server with ChatGPT-plan OAuth:
  https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- Sign in with ChatGPT preview limitations:
  https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- Managing Astra usage/model selection in Work and Codex:
  https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex
- Using Codex with a ChatGPT plan:
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan

## 13. Frozen takeaway

> JARVIS should not use the strongest model because it is available. It should use the weakest/cheapest route that has evidence it can satisfy the current task, then escalate deliberately.

> For software development, JARVIS should increasingly act as the governed engineering manager and use an approved coding specialist such as Codex for the coherent edit/test loop instead of recreating that intelligence from scratch.


## 14. Ephemeral local capability-development brain

The owner has proposed an additional local-first development tier:

- normal JARVIS continues using its ordinary resident/local routing policy;
- when a capability-development mission begins, JARVIS may acquire an exclusive local
  development-intelligence resource;
- the normal resident local model may be evicted if needed;
- a coding-specialist local model is loaded only for the development session;
- the DevelopmentEngine uses it for repository inspection, patch generation, test/fix
  iteration and structured completion when the model is benchmark-qualified;
- difficult/failed cases escalate through the normal cloud ladder (for example Sol-class,
  Codex plan-backed stronger lane, then Astra-class only when justified);
- after the mission, the coding model is unloaded and ordinary JARVIS residency resumes.

This is an extension of the existing C5 local residency controller, not a second local
runtime manager.

### First hardware-appropriate coding candidate

For the owner's RTX 5060 Ti 8 GB / 16 GB RAM machine, do not start with
`qwen3-coder:30b`; Ollama currently publishes that package at about 19 GB, so it is not a
practical fully-resident 8 GB target.

A better first coding benchmark is `qwen2.5-coder:7b` (Q4-class package about 4.7 GB,
32K advertised context). It should be tested with bounded context and the real JARVIS GPU
baseline before admission. Qwen3 8B (~5.2 GB) is a useful general comparator but is not as
code-specialized.

Ollama supports explicit model unloading through `keep_alive: 0` / `ollama stop`.
Because current issue history reports edge cases around concurrent requests and immediate
unload, JARVIS should hold an exclusive local-model lease, stop the coding model after the
session, verify via the runtime process/model-status surface that VRAM was released, and
only then restore normal local residency.

References:
- https://ollama.com/library/qwen2.5-coder
- https://ollama.com/library/qwen3-coder
- https://github.com/ollama/ollama/blob/main/docs/api.md
- https://github.com/ollama/ollama/issues/17004


## 2026-10-04 priority clarification — compression first

The owner has explicitly deferred the ephemeral local capability-development brain.
Do not implement or benchmark a dedicated local coding model in the current slice.

Current order:
1. integrate and benchmark local prompt compression (LLMLingua-2 first);
2. measure semantic equivalence and real ChatGPT-plan token reduction;
3. retain normal existing JARVIS local-brain behavior unchanged;
4. revisit a temporary local coding brain only if compression plus existing/cloud model
   routing still leaves capability-development cost or quota pressure materially high.

This prevents solving a problem that prompt compression may already remove.
