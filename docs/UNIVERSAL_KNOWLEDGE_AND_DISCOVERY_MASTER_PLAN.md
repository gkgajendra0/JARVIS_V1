# JARVIS Universal Knowledge and Discovery Intelligence Master Plan

## Status

**OWNER-APPROVED ADVANCED NORTH STAR — 2026-09-27**

This document defines a long-horizon intelligence program for JARVIS. It is subordinate to
`AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md` and does not replace the current governed
self-repair, self-learning, self-evolution, product-roadmap, or active phase work.

Nothing in this document claims that these capabilities exist in production today.
Implementation must follow the normal JARVIS lifecycle:

```text
research thoroughly
-> architecture
-> owner approval
-> isolated implementation
-> automated validation
-> owner-machine / physical acceptance where required
-> documentation
-> protected promotion
```

The purpose of this plan is to prevent short-term implementation choices from closing the
path toward the owner's advanced long-term goal.

---

## 1. Advanced north star

JARVIS should eventually become capable of two complementary forms of intelligence:

1. **Universal Knowledge Intelligence** — access, verify, organize, connect, retain, and
   reason over as much accessible human knowledge as possible across any domain relevant
   to the owner's objectives.
2. **Discovery Intelligence** — use that knowledge to identify gaps, contradictions,
   anomalies, bottlenecks, underexplored combinations, and unanswered questions; generate
   hypotheses; attempt to falsify them; run computational and eventually physical
   experiments; and learn from the results.

The combined north star is:

> **Understand everything humanity can currently teach us, then investigate what humanity
> has not discovered yet.**

The goal is not omniscience and not a claim that JARVIS can literally contain every fact.
The practical target is that, when the owner asks about an unfamiliar domain, JARVIS can
enter that domain, find the best available knowledge, establish what is known and unknown,
reason over it deeply, and preserve verified learning for future work.

---

## 2. Relationship to the existing JARVIS north star

The current top-level north star remains:

> JARVIS becomes a governed autonomous self-managing personal intelligence runtime while
> owner authority remains constitutionally separate.

Universal Knowledge and Discovery Intelligence extend that goal rather than replacing it.

The progression is:

```text
Personal Intelligence
        ↓
Persistent Autonomous Work
        ↓
Self-Awareness / Self-Repair
        ↓
Governed Self-Learning
        ↓
Governed Self-Evolution
        ↓
Universal Knowledge Intelligence
        ↓
Cross-Domain Reasoning
        ↓
Discovery Intelligence
        ↓
Computational + Physical Discovery
```

Self-repair and self-evolution are important training grounds because they already require
JARVIS to:

```text
observe
-> identify a problem
-> research
-> form a hypothesis
-> build/test a candidate
-> reject or accept it
-> learn from the result
```

Discovery Intelligence applies the same disciplined loop to external reality instead of
only to JARVIS itself.

---

# PART I — UNIVERSAL KNOWLEDGE INTELLIGENCE

## 3. Objective

Build a shared **JARVIS Knowledge Fabric** that every capability can use.

It must not be isolated inside a single "research skill". Coding, engineering, personal
assistance, device work, scientific research, planning, and future discovery should all be
able to use the same knowledge substrate.

The Knowledge Fabric should answer:

- What does humanity currently know about this topic?
- Which sources support that claim?
- How reliable and current is the evidence?
- Where do reliable sources disagree?
- Which assumptions are being made?
- What has JARVIS itself observed or tested?
- What remains unknown?

---

## 4. What the Knowledge Fabric is NOT

The program must explicitly avoid these bad architectures:

- "download the internet into one database";
- "train one gigantic model and assume it now knows everything";
- treat model pretraining knowledge as verified truth;
- keep unbounded duplicated raw text forever;
- store every retrieved statement as durable knowledge;
- allow stale information to remain indistinguishable from current information;
- allow one model provider to become the owner of JARVIS knowledge;
- equate confident language with evidence.

The durable system should be **source-aware, model-independent, selective, updateable,
and evidence-backed**.

---

## 5. Knowledge classes

JARVIS must distinguish at least four different ways of knowing something.

### 5.1 Model knowledge

Information present in the active reasoning model.

Properties:

- fast;
- broad;
- may be stale;
- may be wrong;
- may have weak provenance.

Model knowledge is useful for reasoning but is not automatically durable truth.

### 5.2 Retrieved knowledge

Information fetched for the current task from sources such as:

- web pages;
- technical documentation;
- scientific papers;
- books;
- patents;
- standards;
- datasets;
- APIs;
- code repositories;
- government publications;
- specialist databases.

Retrieved knowledge must retain source identity and retrieval time.

### 5.3 Verified persistent knowledge

Information promoted into durable JARVIS knowledge only after sufficient verification.

A durable claim should be able to retain:

- normalized claim;
- evidence;
- source provenance;
- source quality;
- date/time;
- domain;
- assumptions;
- applicability conditions;
- supporting sources;
- contradicting sources;
- confidence;
- verification status;
- supersession history;
- freshness requirement.

### 5.4 Experience-derived knowledge

Knowledge JARVIS learns by doing.

Examples:

- a library documented as compatible fails under a specific local configuration;
- a hardware command behaves differently from vendor documentation;
- an optimization consistently reduces latency under measured conditions;
- an experiment invalidates an earlier assumption.

Experience-derived knowledge must preserve the original experiment/evidence and must never
silently overwrite external documented knowledge. Both can coexist when conditions differ.

---

## 6. Truth and uncertainty model

Important claims should use explicit epistemic states rather than a single confidence
number.

Minimum states:

- **KNOWN** — strongly supported by reliable evidence within the stated conditions.
- **SUPPORTED_INFERENCE** — not directly proven, but evidence strongly supports it.
- **SPECULATION** — plausible but weakly supported.
- **UNTESTED_HYPOTHESIS** — a proposed explanation/prediction requiring testing.
- **DISPUTED** — credible evidence materially conflicts.
- **UNKNOWN** — available evidence is insufficient.

JARVIS should be able to explain *why* a claim has its state.

---

## 7. Source universe

The architecture should eventually support governed connectors/adapters for:

- peer-reviewed papers and preprints;
- patents;
- textbooks and books;
- technical standards;
- vendor documentation;
- structured scientific databases;
- public datasets;
- open-source repositories;
- conference publications;
- public government sources;
- historical archives;
- engineering manuals;
- domain-specific knowledge bases;
- owner-authorized private sources;
- JARVIS's own verified experiment and operational records.

Access rights, licensing, privacy, and credentials remain governed independently. The
Knowledge Fabric does not gain automatic entitlement to inaccessible information.

---

## 8. Knowledge representation

The implementation technology is intentionally not fixed yet, but the semantic model
should support a structure similar to:

```text
Concept / Claim
  ├── definition
  ├── evidence
  ├── provenance
  ├── conditions
  ├── assumptions
  ├── supporting claims
  ├── contradicting claims
  ├── related concepts
  ├── historical evolution
  ├── experiments
  ├── confidence / epistemic state
  ├── freshness policy
  ├── last verified
  └── open questions
```

Raw documents, semantic indexes, graphs, relational records, embeddings, and specialist
stores may all be useful implementation components, but none should independently become
the canonical truth model.

---

## 9. Knowledge depth router

JARVIS should not perform maximum-cost research for every question.

The system should choose a research depth based on consequence, uncertainty, novelty, and
owner intent.

Example:

```text
simple stable question
    -> model + lightweight verification

current factual question
    -> fresh authoritative retrieval

technical investigation
    -> multi-source deep research + code/docs

high-stakes or disputed question
    -> stronger evidence + contradiction search

scientific investigation
    -> papers + datasets + specialist tools/models

discovery quest
    -> large-scale autonomous investigation
```

This keeps normal JARVIS interaction fast while allowing extreme depth when justified.

---

## 10. Cross-domain reasoning

A major purpose of the Knowledge Fabric is to find relationships humans often miss because
knowledge is separated by discipline.

JARVIS should eventually be able to ask:

- Does a method from field A solve a bottleneck in field B?
- Has a newly available technology invalidated an old assumption?
- Are two communities describing the same phenomenon with different terminology?
- Does an abandoned approach become viable when combined with a newer material,
  algorithm, manufacturing method, or instrument?
- Are multiple independent findings compatible with a shared deeper explanation?

Cross-domain synthesis must preserve the distinction between sourced fact and generated
inference.

---

## 11. Model independence

JARVIS knowledge must outlive the active model provider.

Target architecture:

```text
              JARVIS KNOWLEDGE FABRIC
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   cloud model A   cloud model B   local model
```

OpenAI, Gemini, Claude, local models, or future models may act as reasoning workers.

They must not become the canonical owner of:

- durable JARVIS knowledge;
- provenance;
- experimental results;
- knowledge confidence;
- owner truth;
- discovery history.

This is essential to long-term local independence.

---

# PART II — DISCOVERY INTELLIGENCE

## 12. Objective

Once JARVIS can reliably model existing knowledge, it should begin investigating:

> **Where does human knowledge stop, conflict, or fail to explain what is observed?**

The purpose is not to generate impressive-sounding "revolutionary ideas".

The purpose is to produce hypotheses that remain interesting **after aggressive attempts
to prove them wrong**.

---

## 13. Frontier mapping

JARVIS should maintain domain-specific and eventually cross-domain **Frontier Maps**.

Signals may include:

- unexplained experimental results;
- conflicting high-quality studies;
- repeated assumptions with weak direct testing;
- missing regions in parameter spaces;
- known engineering bottlenecks;
- abandoned approaches that new technology may revive;
- negative results whose cause remains unclear;
- discoveries in one discipline unused in another;
- recent enabling technologies;
- anomalous measurements;
- theories that explain most but not all observations;
- areas where evidence quality is unexpectedly poor.

A Frontier Map is not a list of random unsolved problems. Each candidate should retain
evidence for *why the gap appears real and potentially important*.

---

## 14. Hypothesis engine

For promising frontier items, JARVIS should generate multiple competing hypotheses rather
than converge immediately on one explanation.

Future specialist roles may include:

- physics;
- chemistry;
- materials science;
- mathematics;
- computer science;
- electronics;
- mechanical engineering;
- biology;
- manufacturing;
- economics/business feasibility;
- patent/prior-art analysis;
- cross-domain synthesis;
- adversarial skeptic.

Specialists may use different models or tools, but all work should enter the same governed
Work/Knowledge system.

---

## 15. Falsification engine

This is a core safety and quality requirement.

For every promising hypothesis, JARVIS should actively attempt to destroy it.

Questions include:

- Is the premise false?
- Has this already been tried?
- Is there prior art?
- Does it contradict a well-supported physical constraint?
- Are calculations reproducible?
- Does another explanation fit the evidence better?
- Is an observed effect merely noise, bias, leakage, or confounding?
- Does the idea fail under realistic manufacturing or cost constraints?
- Is the result dependent on a hidden assumption?
- Can an independent model/agent reproduce the conclusion?

A hypothesis becomes more interesting only when meaningful falsification attempts fail.

---

## 16. Novelty and prior-art engine

JARVIS must distinguish:

```text
new to the owner
≠ new to JARVIS
≠ uncommon
≠ new to the research community
≠ genuinely novel
```

Before treating anything as a discovery, JARVIS should search appropriate:

- papers;
- patents;
- preprints;
- databases;
- historical literature;
- open-source implementations;
- technical archives.

"Could not find prior art" is not equivalent to proof that prior art does not exist.
Novelty confidence must be explicit and revisable.

---

## 17. Computational laboratory

Before expensive physical experimentation, JARVIS should exploit computation wherever the
domain permits.

Possible tools include:

- mathematical modelling;
- numerical simulation;
- Monte Carlo methods;
- optimization;
- evolutionary search;
- machine learning;
- circuit simulation;
- finite-element analysis;
- molecular/material simulation;
- digital twins;
- parameter sweeps;
- generated test harnesses;
- automated data analysis.

The exact toolchain must be selected per domain. JARVIS should not pretend that a
simulation proves reality; simulation output is evidence conditioned on the model.

---

## 18. Historical rediscovery benchmark

Before trusting JARVIS on genuinely unknown questions, we should measure whether the
discovery machinery can recover things that humans later discovered.

Method:

1. choose a historical discovery;
2. establish a knowledge cutoff before the discovery;
3. provide JARVIS only information available at or before that cutoff;
4. let it map the frontier, generate hypotheses, and test them;
5. compare the resulting reasoning with the later real discovery;
6. score the process, not merely whether the final answer matched.

This creates a **Discovery Benchmark Suite**.

Useful metrics may include:

- gap-identification quality;
- hypothesis relevance;
- false-positive rate;
- falsification strength;
- experiment quality;
- novelty detection;
- number of independent clues connected;
- compute/cost required;
- reproducibility.

A discovery system that cannot rediscover known historical advances under controlled
conditions should not be trusted to claim unknown ones.

---

## 19. Autonomous Quest Engine

At a mature stage, the owner should not always need to provide the exact research
question.

An owner-approved quest might be:

> Search for important scientific or technological bottlenecks where recent developments
> create a credible new opportunity.

The system may continuously investigate but should surface only evidence-backed candidates.

A useful future report should resemble:

```text
Observation:
Three independent recent developments alter constraints that blocked approach X.

Evidence:
...

Why this may matter:
...

Why it may be novel:
...

Strongest reasons it may fail:
...

What has already been tested:
...

Cheapest decisive next experiment:
...

Required owner decision:
...
```

The Quest Engine remains subordinate to owner goals, resource budgets, and authority.

---

## 20. Physical experimentation

Some hypotheses cannot be validated through software.

Long-term integrations may include:

- cameras and sensors;
- electronics instruments;
- robotic actuators;
- microscopes;
- 3D printers;
- CNC machines;
- measurement equipment;
- chemistry/materials laboratory equipment;
- external research facilities.

Closed loop:

```text
hypothesis
    ↓
experiment design
    ↓
governed execution
    ↓
measurement
    ↓
analysis
    ↓
independent verification
    ↓
knowledge update
    ↓
next experiment
```

Physical safety, credentials, facility rules, spending, and irreversible actions require
their own explicit governance. Discovery does not grant unrestricted physical authority.

---

## 21. Failure becomes knowledge

Failed investigations should be retained when they carry useful evidence.

A failed attempt should be able to record:

- question;
- hypothesis;
- expected result;
- experiment/simulation;
- actual result;
- confidence in measurement;
- likely failure mechanism;
- alternative explanations;
- what was ruled out;
- what remains unresolved;
- follow-up ideas.

The purpose is to avoid repeatedly paying for the same dead end and to allow later
technology to revisit an old failure intelligently.

---

# PART III — INTEGRATION AND GOVERNANCE

## 22. Reuse existing JARVIS foundations

This program should reuse existing primitives rather than create another independent
agent platform.

| Existing JARVIS foundation | Future role |
| --- | --- |
| WorkItem / durable orchestration | long-running research and experiments |
| EngineeringKnowledge | precedent for verified domain knowledge contracts |
| EngineeringChange | governed creation/modification of tools and capabilities |
| Model Router | specialist reasoning/model selection |
| Authority / OPA / audit | action and data-access boundaries |
| Sandbox / provenance | safe computational experiments and reproducibility |
| Self Model | understanding available JARVIS tools/resources |
| Memory/context | owner goals and investigation continuity |
| Self-learning/evolution | learning and tool acquisition mechanisms |
| Hands/device control | future governed effectors and instruments |

The Universal Knowledge Fabric is broader than current EngineeringKnowledge.
Implementation must research whether to extend shared contracts, compose separate stores,
or introduce new canonical objects. It must not casually overload EngineeringKnowledge
with incompatible semantics.

---

## 23. Governance invariants

Greater knowledge must not create greater implicit authority.

Permanent rules:

- knowledge does not equal permission;
- hypothesis does not equal fact;
- simulation does not equal physical proof;
- model consensus does not equal verification;
- JARVIS may not redefine evidence standards to make a hypothesis succeed;
- JARVIS may not silently broaden credentials or data access to improve research;
- protected changes remain governed;
- high-impact physical experiments require explicit safety and authority controls;
- all claimed discoveries require reproducible evidence;
- contradictory evidence must remain visible.

---

# PART IV — PROGRAM SEQUENCE

## 24. Proposed long-term phases

These labels are strategic program stages, not the current numbered implementation phases.

### K0 — Knowledge contracts and truth model

Define:

- claim schema;
- provenance;
- epistemic states;
- contradiction handling;
- freshness/supersession;
- access policy;
- experiment linkage.

### K1 — Federated source and retrieval layer

Build governed adapters for selected high-value source classes and introduce the Knowledge
Depth Router.

### K2 — Verified persistent Knowledge Fabric

Promote selected retrieved claims into durable, source-aware, updateable knowledge.

### K3 — Cross-domain synthesis

Build reliable concept linking, terminology resolution, contradiction analysis, and
cross-domain relationship discovery.

### K4 — Model-independent knowledge service

Make the Knowledge Fabric a core JARVIS service available to all capabilities and usable
by cloud or local reasoning models.

### D0 — Frontier Mapper

Detect and rank evidence-backed gaps, anomalies, contradictions, bottlenecks, and
underexplored regions.

### D1 — Multi-hypothesis reasoning

Generate competing explanations/predictions using specialist workers.

### D2 — Falsification + novelty

Systematically attack hypotheses and search prior art before deeper investment.

### D3 — Computational Laboratory

Run reproducible simulations, models, searches, and analyses through governed sandboxes.

### D4 — Historical Rediscovery Benchmark Suite

Validate the discovery architecture against controlled historical cutoffs.

### D5 — Autonomous Quest Engine

Permit bounded owner-approved long-running searches for high-value discovery candidates.

### D6 — Physical experimentation

Integrate governed instruments, robotics, and external facilities where justified.

### D7 — Continuous Discovery Intelligence

Close the loop:

```text
knowledge
-> frontier
-> hypothesis
-> falsification
-> experiment
-> evidence
-> learning
-> new frontier
```

---

## 25. Entry conditions

Do not start broad Discovery Intelligence merely because the idea is exciting.

Before serious D-stage work, JARVIS should have strong enough foundations in:

- durable autonomous work;
- source-aware research;
- verified persistent knowledge;
- secure sandboxing;
- provenance;
- reproducibility;
- model routing;
- governed capability acquisition;
- closed-loop learning;
- self-evolution;
- cost/resource controls.

A weak truth system combined with a powerful hypothesis generator would mainly produce
convincing nonsense faster.

---

## 26. Success criteria — Universal Knowledge

The Knowledge Fabric becomes credible when JARVIS can reliably:

- enter an unfamiliar domain;
- identify authoritative sources;
- build a structured domain model;
- distinguish fact, inference, dispute, and unknowns;
- preserve source provenance;
- detect stale/superseded knowledge;
- retrieve relevant knowledge later;
- combine multiple disciplines without losing evidence boundaries;
- preserve experience-derived learning;
- switch reasoning models without losing accumulated knowledge.

---

## 27. Success criteria — Discovery Intelligence

Discovery Intelligence becomes credible when JARVIS can:

- identify meaningful knowledge gaps without being directly told where they are;
- generate multiple testable hypotheses;
- reject weak ideas through falsification;
- find known prior art before claiming novelty;
- design decisive experiments;
- reproduce computational results;
- perform well on historical rediscovery benchmarks;
- learn from failed experiments;
- make predictions that can be independently tested;
- preserve complete evidence/provenance;
- produce results reproducible by independent verification.

The ultimate milestone is:

> **Gajendra and JARVIS identify, validate, and independently reproduce a genuinely novel
> result that was not present in the knowledge used to generate it.**

---

## 28. Anti-goals

Do not optimize for:

- appearing omniscient;
- maximum document count;
- maximum agent count;
- maximum autonomous activity;
- speculative "breakthrough" generation;
- confirmation of the owner's preferred idea;
- novelty claims without prior-art work;
- one giant vector database being called intelligence;
- model self-confidence;
- replacing domain experts or physical evidence where they remain necessary.

Optimize for:

- truth;
- useful uncertainty;
- evidence;
- reproducibility;
- falsification;
- accumulated learning;
- cross-domain leverage;
- discoveries that survive independent verification.

---

## 29. Current-program rule

This advanced north star must **not interrupt or renumber the currently active
self-repair/self-evolution engineering program**.

Near-term architecture decisions should simply avoid unnecessarily blocking this future.

When the current governed self-evolution foundation is mature enough, this program should
begin with fresh research and an owner-approved K0 architecture rather than blindly
implementing the technology ideas described here.

---

## 30. Final north-star statement

> **JARVIS should become a governed intelligence that can learn from humanity's accessible
> accumulated knowledge across domains, preserve and connect verified understanding,
> recognize the boundary between known and unknown, and work with Gajendra to investigate
> that boundary through disciplined reasoning, falsification, simulation, and eventually
> real experimentation.**
