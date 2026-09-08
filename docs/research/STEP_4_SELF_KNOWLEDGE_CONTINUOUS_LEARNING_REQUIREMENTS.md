# Step 4 — JARVIS Self-Knowledge and Continuous-Learning Requirements

## Status

**RESEARCH REQUIREMENT — NOT AN APPROVED ARCHITECTURE OR IMPLEMENTATION.**

This note is a companion to `STEP_4_LIVE_CONTEXT_PERSONAL_MEMORY_RESEARCH.md`. It records a critical product requirement discovered during Step 4 research: JARVIS must not only remember the user and past conversations; the memory/context foundation must also support a trustworthy, machine-readable understanding of JARVIS itself so later stages can diagnose failures, learn from outcomes, research better solutions, and improve safely over time.

No runtime self-repair, self-modification, or autonomous deployment is approved by this document.

## Product intent

The long-term goal is not a static assistant that requires the owner to manually investigate every failure.

JARVIS should progressively become capable of:

1. knowing what it is and what product principles govern it;
2. knowing how its current architecture is assembled;
3. knowing what capabilities are actually installed and available;
4. knowing which components, providers, hardware, configuration, and dependencies those capabilities rely on;
5. observing failures and degraded behaviour;
6. using evidence, diagnostics, architecture knowledge, and past incident history to identify likely causes;
7. recognizing repeated failure patterns and architectural weaknesses;
8. researching current mature technologies/solutions before proposing a custom fix;
9. comparing alternatives against JARVIS requirements and measured behaviour;
10. testing candidate repairs/improvements safely;
11. automatically handling low-risk recoverable failures where policy permits;
12. escalating higher-risk permanent changes for approval;
13. retaining useful outcome evidence so future decisions improve rather than restarting from zero.

The desired long-term loop is:

```text
USE JARVIS
   |
   v
observe results / failures / corrections / latency / quality
   |
   v
retain useful evidence and outcomes
   |
   v
detect weakness, recurring incident, or capability gap
   |
   v
research CURRENT existing solutions first
   |
   v
compare mature technology vs current implementation
   |
   v
propose candidate improvement
   |
   v
test / benchmark / validate in isolation
   |
   v
apply only within authority policy
   |
   v
observe outcome
   |
   +--> keep if better
   |
   +--> rollback if worse
   |
   v
continue learning
```

This is the same research-first principle used by the human development process today, but eventually represented as an explicit JARVIS capability rather than an undocumented human habit.

## Why this belongs in Step 4

Actual self-diagnosis, self-repair, and governed self-improvement belong to later stages because they require observability, capability execution, permissions, testing, rollback, and deployment controls.

However, Step 4 must establish the **knowledge and memory foundation those later stages will consume**. If Step 4 is designed only around personal preferences such as `user likes X`, it may create a memory model that cannot reliably represent architecture, provenance, incidents, outcomes, or changing system state.

Therefore Step 4 must account for self-knowledge now even though it does not implement autonomous repair now.

The intended separation is:

| Responsibility | Step 4 foundation | Later capability |
| --- | --- | --- |
| Live conversation context | Yes | — |
| Personal semantic memory | Yes | — |
| Episodic memory | Yes | — |
| Reflection / learning candidates | Yes | Later consumers use them |
| JARVIS identity/self-description | Yes | — |
| Architecture/component knowledge | Yes | Diagnostics consume it |
| Capability/dependency knowledge | Yes | Capability runtime consumes it |
| Incident/outcome memory schema | Yes | Repair/learning consumes it |
| Runtime health observation | No | Observability/diagnostics stage |
| Root-cause analysis | No | Later diagnostics stage |
| Automatic routine recovery | No | Later repair stage |
| Technology research / upgrade proposal | No | Later improvement stage |
| Permanent self-modification | No | Governed self-improvement stage |
| Deployment / rollback authority | No | Governed self-improvement stage |

## Self-knowledge is not ordinary personal memory

JARVIS must not treat statements about its own architecture like ordinary remembered preferences.

Example failure:

```text
memory says: audio input = device index 57
runtime configuration changed yesterday
```

If memory is allowed to outrank current configuration, JARVIS will diagnose itself using stale information.

Self-knowledge therefore needs explicit source-of-truth and authority semantics.

## Required self-model domains

### 1. Identity — “What am I?”

Examples:

- product purpose;
- current version/build identity;
- core operating principles;
- security/authority principles;
- research-first implementation principle;
- local-first/privacy constraints;
- what JARVIS must never self-authorize.

### 2. Architecture — “How am I built?”

Examples:

- components/services/modules;
- authoritative owners;
- data/control flow;
- interfaces;
- provider boundaries;
- hardware dependencies;
- storage systems;
- network/external dependencies;
- security boundaries.

### 3. Capability registry — “What can I actually do?”

This must describe installed/available capabilities, not generic model knowledge.

Possible fields include:

- capability ID;
- purpose;
- current implementation/provider;
- required components;
- required permissions;
- hardware requirements;
- configuration dependencies;
- health test;
- known limitations;
- fallback implementation;
- risk/authority level.

Examples might eventually include:

```text
voice.listen
voice.wake_detect
vision.track_person
camera.pan
memory.retrieve
```

### 4. Dependency knowledge — “What depends on what?”

JARVIS must be able to reason from a failed capability to plausible upstream dependencies.

Example:

```text
voice interaction
   -> microphone endpoint
   -> audio routing
   -> wake detector
   -> voice session
   -> realtime provider
   -> conversation owner
```

The dependency graph should be derived from authoritative architecture/capability declarations where possible rather than guessed by an LLM.

### 5. Configuration provenance — “What is configured now, and who owns that truth?”

Current configuration values should be read from their authoritative configuration/runtime sources when needed.

Durable memory may retain configuration **history/outcomes**, but it should not silently become the source of current runtime truth.

### 6. Test and diagnostic knowledge — “How can this component prove that it works?”

Later diagnostics should be able to discover:

- component health checks;
- relevant automated tests;
- smoke tests;
- known diagnostic commands/APIs;
- expected healthy signals;
- safe recovery actions;
- dependencies that should be inspected first.

Step 4 only needs to ensure this knowledge can be referenced/provenanced. It does not implement the diagnostic executor.

### 7. Incident and outcome memory — “What happened before?”

Step 4 episodic memory must be able to represent system incidents and outcomes, not only user-life events.

A useful future incident record should be able to capture:

```text
incident ID
component/capability affected
observed symptom
timestamps
runtime/environment context
diagnostic evidence
suspected causes
confirmed root cause
actions attempted
research/source references
repair applied
tests performed
outcome
regressions / side effects
final accepted resolution
rollback information
confidence / verification
```

This does not mean every log line becomes durable memory. Raw logs should remain in observability/log storage according to retention policy; memory should preserve the meaningful incident/outcome summary plus provenance to evidence.

## Declared vs learned self-knowledge

The self-model must distinguish at least two categories.

### Declared self-knowledge

Facts established by authoritative project/runtime sources, for example:

- repository code;
- architecture documents;
- ADRs;
- capability declarations;
- configuration;
- dependency metadata;
- tests;
- security/authority policy.

This is the strongest class for answering “how am I built?” and “what is configured now?”.

### Learned self-knowledge

Evidence-backed observations discovered through operation, for example:

- camera tracking repeatedly degrades under a particular condition;
- a certain failure usually follows a specific Windows audio change;
- one provider performs better for a measured task class;
- a repair resolved a recurring incident several times;
- a component is showing increasing failure frequency.

Learned self-knowledge must carry provenance, time, evidence, confidence, and validity. It is a hypothesis/observation until verification rules promote it.

**Learned observation must never silently overwrite declared architecture or current runtime truth.**

## Source authority hypothesis

The following authority ordering is a research hypothesis that must be refined during Step 4 lifecycle research:

### Current runtime/configuration facts

Authoritative runtime/configuration source > cached observation > durable historical memory > model inference.

### Architecture/component facts

Repository/approved architecture/ADR/capability declaration > generated summary > learned inference.

### Why a technology/architecture decision was made

Approved ADR/research record > remembered conversation summary > model inference.

### Past incident/outcome

Verified incident record + evidence > reflection summary > inferred pattern.

### Improvement hypothesis

Measured evidence + current research > prior learned pattern > model intuition.

The memory system must preserve the source class so retrieval can respect these differences.

## Continuous learning does not mean unrestricted mutation

The desired JARVIS is increasingly independent, but independence must remain governed.

### Examples of future low-risk actions that may eventually be automatic

Subject to later policy and implementation:

- retry a failed connection;
- restart a crashed replaceable component;
- switch to an already-approved healthy fallback;
- rebuild a derived cache/index;
- run diagnostics;
- collect evidence;
- restore a known-good transient state.

### Examples of future actions that may be researched/tested automatically but normally require approval

- replace a core library;
- change architecture;
- install new privileged software;
- modify security-sensitive configuration;
- change authority boundaries;
- merge permanent code changes into protected main;
- alter persistent privacy/security policy.

### Actions JARVIS must never self-authorize merely to make itself more powerful

Examples include weakening its own security/authority boundaries, bypassing required approval, or redefining the rules that govern its own permissions.

The governing principle is:

> **JARVIS may become better at operating within its authority; improvement is not permission to expand its own authority.**

## Research-first self-improvement requirement

When a recurring weakness or capability gap is detected in the future, JARVIS should not immediately generate custom code.

The intended decision process is:

```text
problem / weakness detected
        |
        v
inspect architecture + evidence + previous incidents
        |
        v
form diagnosis / requirement
        |
        v
research current existing technologies and proven solutions
        |
        v
compare suitable mature options
        |
        +--> existing solution satisfies requirement -> adapt/integrate it
        |
        +--> no adequate solution -> only then consider custom component
        |
        v
benchmark against current implementation
        |
        v
propose / test / validate under authority policy
```

This rule must eventually be represented in self-improvement policy and supporting metadata, not merely kept as a prompt instruction.

## Step 4 memory implications

The Step 4 canonical lifecycle/schema research must therefore consider more than user facts.

At minimum it must be able to support or reference:

- personal semantic facts/preferences;
- user/project episodes;
- system incidents/outcomes;
- source/provenance IDs;
- temporal validity;
- confidence/verification;
- supersession/retraction/deletion;
- subject/scope distinctions (`user`, `project`, `jarvis`, `capability`, `component`, etc.);
- declared vs learned knowledge;
- source authority/trust class;
- evidence/reference links;
- sensitivity/privacy class;
- durable vs transient status.

The exact schema is **not selected yet**.

## Step 4 retrieval implications

Future retrieval must not simply ask a vector database for “similar memories” and feed all results to a model.

For self-knowledge, retrieval must be capable of respecting:

1. subject/scope;
2. current vs historical truth;
3. declared vs learned knowledge;
4. source authority;
5. verification state;
6. temporal validity;
7. sensitivity/permission;
8. provenance/evidence availability.

Example: if diagnosing the current microphone configuration, runtime configuration should be consulted rather than an old incident memory that happens to be semantically similar.

## Relationship to later self-repair/evolution work

A possible future dependency chain is:

```text
Step 4 context + memory + self-knowledge foundation
          |
          v
observability / runtime health
          |
          v
diagnostics / root-cause analysis
          |
          v
incident learning and pattern detection
          |
          v
safe routine repair
          |
          v
capability-gap detection
          |
          v
current-technology research + benchmark
          |
          v
governed improvement proposal
          |
          v
isolated modification/test
          |
          v
approval when required
          |
          v
deploy / observe / rollback
```

Later roadmap planning may assign different step numbers. This document intentionally does not renumber or pre-approve later roadmap stages.

## Additional Step 4 research questions created by this requirement

Before Step 4 architecture approval, research must answer at least:

1. What should be canonical memory versus dynamically derived from repository/config/runtime?
2. How should a machine-readable self-model reference architecture sources without duplicating them into stale memory?
3. What stable IDs are needed for components, capabilities, sessions, turns, incidents, evidence, and decisions?
4. Should the capability/dependency registry be declarative files, generated metadata, code registration, or a hybrid?
5. How should approved ADR/research decisions be made queryable to JARVIS without treating free-form documentation as unrestricted prompt context?
6. How should learned operational observations be promoted, contradicted, expired, or rejected?
7. How should incident summaries reference raw logs/traces without retaining unnecessary sensitive data in durable memory?
8. How should repository/web/email/file/tool content be prevented from poisoning self-knowledge?
9. Which operations may eventually be automatically repaired, and how will risk/authority be represented?
10. How should self-improvement experiments record baseline, candidate, tests, metrics, result, and rollback status?
11. How will JARVIS know that a technology/library/version has become outdated without converting general web content into trusted system truth?
12. How will architecture/documentation drift be detected and reconciled?
13. How can self-knowledge remain provider/model-independent so changing the LLM does not erase JARVIS's understanding of itself?

## Acceptance implication for Step 4 research

Step 4 research is incomplete if it produces only a good personal-memory database.

Before architecture approval, the proposed foundation must also demonstrate that it can later support:

- trustworthy JARVIS self-knowledge;
- provenance-rich incident/outcome memory;
- distinction between declared and learned system knowledge;
- source-authority-aware retrieval;
- future diagnostics and repair without transferring architectural truth to an LLM;
- continuous improvement without uncontrolled self-modification;
- replacement of models/providers/frameworks without losing JARVIS's accumulated knowledge and experience.

## Current conclusion

The target is **not** “give the LLM a memory plugin.”

The target is a JARVIS-owned context, memory, provenance, and self-knowledge foundation that can survive model/provider changes and can later power an increasingly independent system that:

```text
knows itself
    -> observes itself
    -> remembers outcomes
    -> detects weaknesses
    -> researches existing solutions
    -> tests improvements
    -> repairs what policy allows
    -> escalates what requires judgement
    -> learns from the result
```

That end-state must influence Step 4 architecture research now, even though autonomous diagnostics, repair, and self-modification are intentionally deferred to later governed stages.
