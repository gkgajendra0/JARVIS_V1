# JARVIS Cost Optimization Master Plan

Status: **OWNER-DIRECTED DESIGN / IMPLEMENTATION NEXT CHAT / NO RUNTIME CHANGE IN THIS PR**

Date: 2026-09-29

Related decisions: `JARVIS_COST_OPTIMIZATION_DECISIONS.md`

## 1. Goal

Make JARVIS economically sustainable for continuous personal use while preserving the North Star: strong autonomy, natural voice UX, correctness, security, owner authority and the ability to escalate to frontier intelligence when genuinely required.

Target whole-system operating envelope:

- approximately **₹3,000–₹4,000/month** for normal JARVIS operation;
- initial paid-brain experiment: approximately **₹400–₹500**;
- the experiment is for measurement and proof, not unrestricted paid autonomy.

The optimization objective is:

> **Use the cheapest sufficient intelligence path, not the cheapest model at any cost.**

## 2. What is already true

JARVIS already has a strong routing foundation under `src/jarvis/model_routing/` from Phase 4:

- target registry;
- deterministic eligibility;
- provider/model health and cooldown;
- bounded fallback;
- versioned routing strategy;
- persisted routing decisions/attempts;
- routing provenance;
- room for cost metadata;
- future local-provider extensibility.

Phase 4 intentionally scoped this to bounded background engineering work. It is therefore a foundation to generalize, not a system to replace.

The current voice runtime still creates realtime cloud sessions directly, and scripted lifecycle speech currently prefers cloud TTS with a local Windows fallback.


### 2.1 Implementation research checkpoint — 2026-09-29

Fresh inspection of the current repository confirms that cost optimization should evolve existing contracts instead of adding parallel infrastructure:

- `src/jarvis/model_routing/models.py` already models target cost profiles, per-attempt usage/estimated cost and aggregate outcome usage/estimated cost.
- `src/jarvis/model_routing/store.py` already persists routing decisions and attempts durably in the canonical WorkStore database.
- `src/jarvis/hands/provider_adapters.py` currently validates structured provider output but does not propagate provider usage metadata back to routing. This is the main C1 instrumentation seam.
- `src/jarvis/voice/livekit_session.py` creates realtime cloud sessions directly from the active provider credential, confirming that voice/TTS and paid-reasoning credential boundaries need explicit separation.
- `src/jarvis/model_routing/router.py` is still scoped to bounded background work and currently builds Gemini/OpenAI cloud targets. It should be generalized rather than replaced.

Therefore the first implementation objective is **observability, not model replacement**. JARVIS should know exactly which subsystem invoked which intelligence path, how often, with what context/usage, latency, retry behavior and estimated cost before optimization decisions are trusted.

## 3. Cost domains

For planning purposes, separate costs into:

### 3.1 Zero/near-zero API-cost execution

- deterministic Python/business logic;
- Git, Docker, tests and file operations;
- local device/network capability execution;
- local retrieval;
- local models on owner hardware;
- cached/verified knowledge reuse;
- local fallback speech.

### 3.2 Potential paid API execution

- cloud LLM reasoning;
- realtime cloud conversational intelligence;
- cloud STT/audio reasoning when used;
- cloud TTS when outside a legitimate free allowance;
- cloud vision reasoning;
- research/search providers;
- memory-related model calls;
- Hands/computer planning;
- autonomous engineering/capability-creation reasoning;
- retries/fallbacks.

The largest optimization opportunity is to stop using paid generative intelligence for work that is deterministic, locally solvable, already known, or safely handled by a cheaper decision/reasoning tier.

## 4. Voice/TTS policy

### 4.1 Current planning assumption

Routine TTS is treated as **₹0 incremental paid-brain cost** while the owner's legitimate Gemini Developer API Free Tier continues to serve the desired voice UX within normal limits.

Use separate project/credential boundaries for:

- free-tier voice/TTS output;
- paid brain/reasoning experiments.

Do not rotate accounts/projects to evade provider limits.

### 4.2 UX invariant

Reasoning engine and voice identity are separate concerns.

A response may be produced by:

- deterministic logic;
- Jev decision layer;
- local brain;
- cheap cloud brain;
- strong cloud brain;

and still be spoken through the same preferred JARVIS TTS voice.

Local reasoning must **not** imply robotic local speech.

### 4.3 Resilience

Free-tier availability is not a permanent architectural assumption.

Retain a local TTS fallback so JARVIS remains usable if free-tier quota, model availability, terms or pricing change.

## 5. Global Brain Router

The existing Phase-4 Model Router should evolve into the common whole-JARVIS intelligence-routing substrate.

Do **not** create a parallel router.

The first question must become:

> **Does this request require generative intelligence at all?**

Target flow:

```text
Request / event
      |
      v
Deterministic eligibility / known capability check
      |
      +--> deterministic / cached / known execution --> local execution
      |
      v
Bounded decision required?
      |
      +--> Jev or local decision fallback
      |
      v
Reasoning required?
      |
      +--> local brain
      |
      +--> cheap cloud
      |
      +--> standard cloud
      |
      +--> strong/frontier cloud
```

Cloud escalation is allowed when it improves expected correctness, latency or total mission cost.

## 6. Three distinct intelligence layers

### 6.1 Deterministic layer

Use ordinary code for facts/rules that do not need AI.

Examples:

- test exit code interpretation;
- known capability lookup;
- device state checks;
- retries/cooldowns defined by policy;
- authorization/owner gates;
- Git/process/file operations;
- exact lifecycle state transitions.

Never spend model tokens to answer a question deterministic code already knows.

### 6.2 Decision layer — Jev candidate

Jev is a candidate specialized **System-1 / bounded decision engine** inside the Global Brain Router.

Its role is not to write prose or solve deep technical problems. Its role is to cheaply answer bounded questions such as:

- deterministic vs local vs cloud route;
- task classification;
- whether web research is required;
- retry vs escalate;
- cheap vs strong reasoning tier;
- tool/capability selection among approved options;
- whether confidence is low enough to escalate.

Important constraints:

- deterministic rules run before Jev;
- Jev cannot grant Authority or bypass owner gates;
- Jev output is advisory routing evidence, not truth;
- confidence/probabilities are signals, not verification;
- Jev is a new external dependency and must be benchmarked against JARVIS-specific decisions;
- JARVIS must keep a local/deterministic fallback if Jev is unavailable;
- current provider pricing/terms must be re-verified immediately before integration.

### 6.3 Reasoning layer

Actual reasoning/generation happens after routing.

Preferred ladder:

1. local efficient brain;
2. local stronger brain if hardware permits;
3. cheap cloud model;
4. standard cloud model;
5. strong/frontier model only when justified.

The goal is not "never use cloud." The goal is to make strong paid cloud reasoning **rare and evidence-driven**.

## 7. Local Brain program

A capable local brain is a first-class cost-control component.

The model must be selected by **JARVIS workload benchmarks**, not generic leaderboard rank.

Candidate runtime/model families should be researched fresh before implementation. The local evaluation should test:

- bounded intent classification;
- structured output;
- tool/capability selection;
- log/error classification;
- WorkStep summarization;
- memory extraction;
- routine planning;
- SQL/Python/code generation;
- small code repair;
- test-failure diagnosis;
- research-result synthesis;
- escalation decisions.

Measure:

- correctness;
- structured-output validity;
- latency;
- tokens/second;
- VRAM/RAM use;
- context limits;
- failure modes;
- percentage of tasks safely kept off paid APIs.

Owner hardware constraint: RTX 5060 Ti, 8 GB VRAM, 16 GB system RAM.

Local models should receive **retrieved relevant evidence**, not the entire repository/history whenever avoidable.

## 8. Retrieval before bigger models

Improve/reuse local retrieval so small models see only relevant context.

Prefer:

```text
task
 -> retrieve exact relevant repo/knowledge/memory/log evidence
 -> compact grounded context
 -> local reasoning
```

over:

```text
task
 -> send giant repo/history to a large cloud model
```

Reuse existing EngineeringKnowledge exact/FTS/hybrid retrieval and verified knowledge before creating another retrieval system.

Context reduction is both a local-model enabler and a direct cloud-token optimization.

## 9. Claude position

Claude subscription/Claude Code is an **optional development-cost accelerator**, not the JARVIS runtime brain contract.

Potential use:

- repository inspection;
- coding;
- refactoring;
- tests;
- debugging;
- candidate implementation during autonomous engineering.

Rules:

- do not assume a Claude monthly subscription provides general Claude API credits;
- subscription-authenticated Claude Code/Agent SDK behavior and limits can change and must be re-verified before integration;
- keep it behind an optional adapter/worker boundary;
- JARVIS must remain functional without Claude subscription availability;
- do not use Claude Code as a workaround for unrelated always-on assistant inference.

## 10. Cost telemetry

Before the paid experiment, every routed model invocation relevant to the experiment must be attributable to:

- mission/work ID;
- subsystem;
- stage;
- provider;
- model/target;
- route tier;
- input usage;
- output usage;
- retries/fallbacks;
- latency;
- estimated provider currency cost;
- estimated INR cost using an explicitly dated conversion basis;
- success/failure/verification outcome.

Mission-level aggregation must make it possible to answer:

```text
Research       ₹X
Architecture   ₹Y
Development    ₹Z
Debugging      ₹A
Verification   ₹B
Fallbacks      ₹C
Total          ₹T
```

No raw secrets should enter telemetry.

## 11. Cost Governor — later protection

Do not lead with a hard governor before routing economics are known.

After real measurements, add:

- monthly budget;
- daily budget;
- per-mission budget;
- strong-model budget;
- retry/fallback budget;
- owner gate before exceeding configured limits;
- fail-closed behavior when budget authority is exhausted.

Optimization reduces spend. The Cost Governor limits damage if optimization fails.

## 12. Pre-paid-experiment gate

Do not buy/use the approximately ₹400–₹500 paid-brain experiment budget until all of the following are true:

1. TTS/voice-output credentials are separated from paid-brain credentials.
2. The existing router has a first global-routing slice rather than engineering-only target selection.
3. Deterministic/known capability routing exists before model invocation.
4. At least one local model has been benchmarked on JARVIS-specific tasks and admitted only for tasks it passes.
5. Jev has been researched/benchmarked as a decision-layer candidate or explicitly deferred with rationale.
6. Cheap-cloud and strong-cloud targets are genuinely distinct tiers rather than labels on equivalent targets.
7. Bounded escalation/fallback works.
8. Per-call and per-mission cost telemetry is available.
9. Owner authority and all existing safety/governance gates remain unchanged.
10. Voice UX has not been knowingly degraded merely to reduce cost.

## 13. First paid experiment

After the pre-paid gate passes:

- purchase approximately ₹400–₹500 of paid brain capacity;
- run one controlled blind real-world capability-acquisition mission;
- the planned TV-control capability is an appropriate candidate;
- do not provide hidden protocol/IP/library clues that would contaminate the blind test;
- preserve legitimate owner pairing/approval gates;
- measure every paid model stage and retry;
- verify real physical effect and rollback/disable behavior.

The experiment must answer:

1. Can JARVIS autonomously acquire the capability within governance?
2. What did each stage cost?
3. What percentage of reasoning remained local/zero-cost?
4. Where did cloud escalation actually add value?
5. Which subsystem should be optimized next?

## 14. Success criteria

The program is successful when:

- routine known actions do not require generative cloud reasoning;
- a substantial share of ordinary reasoning is handled locally;
- Jev or equivalent bounded decision logic demonstrably saves more expensive calls than it adds;
- strong cloud models are exception paths;
- repeated failures do not create uncontrolled token loops;
- cost is attributable per mission;
- the same JARVIS voice/personality UX is preserved;
- owner authority is unchanged;
- whole-system monthly spend can plausibly remain inside the target envelope under normal use.

## 15. Permanent architectural principle

> **Rules decide what rules can decide. A cheap decision layer routes ambiguous bounded choices. Local intelligence handles routine reasoning. Cloud intelligence escalates only when its expected value justifies its cost. JARVIS speaks with one consistent voice regardless of which brain solved the task.**
