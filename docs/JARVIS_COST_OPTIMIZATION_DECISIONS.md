# JARVIS Cost Optimization Decisions

Status: **DESIGN DISCUSSION / NO RUNTIME IMPLEMENTATION AUTHORIZED**

Date: 2026-09-29

## Purpose

Record owner-approved cost assumptions and the next optimization topics before enabling broader paid API use.

The target operating envelope remains approximately **₹3,000–₹4,000 per month for the whole JARVIS system**, not for one subsystem.

## Decision 1 — Keep TTS outside the paid-brain budget for now

The owner currently uses Gemini Developer API Free Tier successfully for TTS and has not observed the TTS quota exhausting in normal use.

Current planning therefore treats routine JARVIS TTS as **₹0 incremental paid-brain cost while legitimate Free Tier quota remains available**.

Planned separation:

- one Gemini project/API key for free-tier TTS / voice-output use;
- a separate paid project/API key for paid reasoning and autonomous work;
- initial paid-brain experiment budget approximately ₹500;
- no runtime change is authorized by this document;
- do not design the product around free TTS being permanent;
- retain a local TTS fallback so JARVIS can continue operating if free-tier availability, limits, pricing, or model availability change.

This decision does **not** authorize account/project rotation to evade service limits.

## Decision 2 — Optimize intelligence usage before replacing good voice UX

Because current TTS is effectively free to the owner, do not degrade the current voice experience merely to reduce a cost that is not presently being paid.

Near-term cost work should focus on paid reasoning and autonomous-intelligence paths instead.

## Next optimization topics

Discuss and design, before implementation:

1. **Global Brain Router**
   - extend routing beyond background engineering work;
   - first decide whether any paid model is needed;
   - prefer deterministic execution, existing capabilities, cached/verified knowledge and local models before cloud reasoning;
   - select the cheapest sufficient cloud target only when needed.

2. **Realtime cloud-brain activation**
   - understand when a cloud realtime session is actually required;
   - avoid paid reasoning for trivial lifecycle or already-known capability execution where possible without damaging UX.

3. **Background work / capability acquisition**
   - measure and reduce repeated research, architecture, coding, debugging and retry calls;
   - reuse verified engineering knowledge and prior solutions;
   - escalate model strength only on evidence of need.

4. **Hands / computer planning**
   - known reliable operations should become direct capability execution;
   - model planning should be reserved for ambiguous or novel actions.

5. **Memory model calls**
   - evaluate candidate extraction, semantic-recall planning and release verification for value versus API cost;
   - move suitable work to local/deterministic paths.

6. **Context/token size**
   - avoid repeatedly sending large conversation histories, logs, repository state or WorkStep evidence when bounded retrieval/summaries are sufficient.

7. **Research-provider usage**
   - measure search/research calls separately from reasoning-model calls and avoid repeated searches for already verified/current evidence.

8. **Cost observability and governor**
   - attribute provider usage by subsystem/mission;
   - track tokens, calls, retries and estimated currency cost;
   - later enforce daily/monthly/per-mission limits after routing economics are understood.

## Architectural principle

> JARVIS should use the cheapest sufficient intelligence path while preserving the desired UX, correctness, safety, owner authority and autonomy.

Cost optimization must not mean making JARVIS noticeably slower, less natural, less capable, or less reliable merely to minimize API spend.


## Decision 3 — Optimize minimally before buying paid brain credits

Do **not** buy paid API credits and immediately run capability-acquisition experiments against the known current routing inefficiencies.

Also do **not** wait for every possible cost optimization to be complete before testing.

The agreed sequence is:

1. separate TTS/voice-output billing from the paid-brain project so routine free-tier TTS does not consume the paid experiment budget;
2. evolve the existing Phase-4 Model Router toward the first Global Brain Router slice, with deterministic/local/cheap-model-first routing and stronger-model escalation only when justified;
3. add enough usage telemetry to attribute provider, model, calls, tokens, retries, stage and estimated cost to a mission;
4. then purchase approximately **₹400–₹500** of paid brain capacity;
5. run a controlled blind real-world capability-acquisition experiment;
6. inspect actual stage-by-stage cost and optimize the components demonstrated to be expensive.

The initial ₹400–₹500 purchase is therefore an **instrumented experiment budget**, not a general authorization for unrestricted paid autonomous operation.

The experiment should answer both:
- did JARVIS complete the capability autonomously within the existing owner/governance gates?;
- what did the successful or failed attempt actually cost, by stage and model path?

A later Cost Governor should enforce hard budgets after these real measurements exist.


## Decision 4 — Local Brain is a first-class cost-control tier

The Global Brain Router should not choose only between Gemini and OpenAI.

The target intelligence ladder is:

1. deterministic/known capability;
2. bounded decision layer;
3. local efficient brain;
4. local stronger brain where hardware permits;
5. cheap cloud;
6. standard cloud;
7. strong/frontier cloud only when justified.

The local brain is selected by JARVIS-specific benchmark results on the owner's hardware, not by generic model popularity.

Local reasoning must not change the preferred JARVIS voice. Reasoning and TTS remain separate layers.

## Decision 5 — Jev is the preferred candidate for bounded AI decisions

Jev should be evaluated as a specialized low-cost decision engine inside the Global Brain Router.

Appropriate decisions include route selection, retry/escalate, task classification, whether research is needed, approved tool/capability choice and local-vs-cloud/cheap-vs-strong selection.

Permanent boundaries:

- deterministic policy runs before Jev;
- Jev cannot grant Authority, bypass owner gates or determine verification truth;
- Jev must be benchmarked against JARVIS-specific decisions;
- a deterministic/local fallback is required if Jev is unavailable;
- current pricing, service maturity and terms must be re-verified before implementation.

## Decision 6 — Retrieval/context optimization is part of local-brain economics

Prefer retrieving relevant repo, EngineeringKnowledge, memory, log and prior-solution evidence before reasoning.

Do not compensate for poor retrieval by continuously sending the full repository, large histories or broad WorkStep evidence to expensive models.

A smaller grounded local model is preferred over a larger cloud model when the smaller model meets the task's correctness and latency requirements.

## Decision 7 — Claude is optional development acceleration, not the runtime brain

Claude Pro/Claude Code may be evaluated for software-development work because subscription-backed coding usage may reduce development cost.

It must remain optional and adapter-bounded.

Do not assume a Claude subscription provides general Claude API credits or permanent Agent SDK entitlement. Re-verify Anthropic's current terms immediately before any integration.

## Decision 8 — Cost optimization implementation order

The authoritative architecture and implementation sequence are now:

- `JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md`
- `JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md`

The next chat should begin from Slice C0 (baseline/call inventory) and continue through the documented pre-credit gate before purchasing the ₹400–₹500 paid-brain experiment balance.
