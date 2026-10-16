# Step 4 memory decisions — research and shadow-only pilot (2026-10-16)

## Scope and decision

**PROPOSED / RESEARCH-ONLY. NOT AN ACCEPTANCE OR PRODUCTION ENABLEMENT.**

Goal: improve (1) Phase 4.4 implicit memory-candidate selection and consolidation, and
(2) Phase 4.5E task-conditioned proactive memory usefulness without unsafe influence.
Do not conflate these with Phase 4.5D explicit, provider-verified recall.

The initial change consists only of a **dependency-free typed shadow-evaluation seam
and tests**, disconnected from LiveKit, `ContextAssembler`, canonical SQLCipher/DPAPI
storage, `MemoryService`, external providers and all deployment/activation paths.
Neither implicit durable admission nor automatic context injection is enabled.
No feature flag is added because there is no production wiring to enable.

Owner has paused D8/universal autonomous capability acquisition. This memory
research must remain standalone: do not merge draft PR #250 JEV or activate D8/GICC.

## Historical research audit: do not repeat old work

Existing durable evidence:
- `docs/PROJECT_STATE.md` and PR #259: production SQLCipher 4.17/DPAPI,
  explicit voice save, restart persistence and deterministic exact retrieval
  owner-machine accepted; semantic cloud recall remains a separate deferred gate.
- Historical Step-4 `STEP_4_BAKEOFF_RESULTS.md`: 30,000-row SQLite temporal/FTS5
  owner-machine benchmark; Qwen3-Embedding-0.6B 256d + FTS5 + equal RRF +
  top-three Qwen3-Reranker-0.6B selected with 100% Recall@1 on the **small
  fixed test corpus**. That number is not universal accuracy.
- `STEP_4_PHASE_4_4_IMPLEMENTATION_RESULT.md`: Gemini Flash-Lite 14/14
  *provider-eligible* production-aligned extraction cases; owner-machine
  session-local quarantine/disposal passed, **zero permanent admission**.
- Historical `STEP_4_PHASE_4_5D_DEFERRED_CLOSURE.md`: independent multilingual
  answerability classifiers failed strict gates; same-provider bounded explicit
  recall later accepted separately in PR #21.
- Historical `STEP_4_PHASE_4_5E_DEFERRED_CLOSURE.md`: Qwen retrieval shadow
  functional, but unrelated memories were also retrieved. ESSENTIAL/HELPFUL/
  UNNECESSARY/STEERING_RISK Qwen prompt-classifier (64-case multilingual
  holdout) had zero ESSENTIAL/HELPFUL recall and four unsafe false influences.
  Experimental branches are explicitly **not approved for main**.
- Step-4 original memory architecture already reviewed Mem0, Graphiti/Zep,
  Letta, LangGraph and temporal SQLite; MemCompiler was reviewed as literature
  in 4.5E. No evidenced Jarvis-specific LangMem/Hindsight/MemCompiler
  comparative owner-machine pilot. This is a narrow gap, not a blank-slate
  memory-stack selection.

All past exposed V4, 4.5D, 4.5E holdouts and retired cases are **not valid**
for tuning, model selection or claims of fresh generalization.

## New external evidence (checked 2026-10-16)

| Candidate | New information | Boundary / disposition |
| --- | --- | --- |
| LangMem | Stateless `create_memory_manager` can propose insert/update/delete; background integration available. | Benchmark **isolated proposal generation**; no direct store-manager access to canonical SQLCipher. Disable mutation; external LLM requires approved data boundary. |
| Hindsight | Self-hosted retain/recall/reflect, Windows support, local embedded PostgreSQL; fact/entity/observation system. | Comparator in disposable isolated environment only. New storage/LLM/runtime cost and no direct compatibility with JARVIS DPAPI truth model. |
| MemCompiler | May-2026 *state-conditioned memory compilation* improves embodied-agent benchmarks vs monolithic injection. | Adapt its textual task-brief idea. Its latent/learned executor mechanism is NOT a demonstrated plug-in for Gemini Live or private multilingual chat. |
| Mem0 (current) | Managed platform advertises strong long-context benchmarks, with proprietary managed-vs-OSS differences. | Research comparator, not a canonical-store replacement. Its current ADD-only accumulation is not a substitute for JARVIS corrections/forget. |
| Memory-R1/MemRL | Outcome-trained write/update/noop or utility-value retrieval techniques. | Later research only; needs reliable outcome labels/compute and must not grant write authority. |
| JEV | PR #250 includes bounded typed Choice client and an eight-case / 24-call Phase-9 candidate-selection acceptance, **not memory tests**, and is draft. | Challenger only after dedicated privacy, consent, memory-specific blinded evaluation; no inheritance of 0.95 threshold. |

Primary external sources:
- https://github.com/langchain-ai/langmem/blob/main/docs/docs/guides/extract_semantic_memories.md
- https://github.com/langchain-ai/langmem/blob/main/docs/docs/background_quickstart.md
- https://github.com/vectorize-io/hindsight
- https://hindsight.vectorize.io/developer/installation
- https://arxiv.org/abs/2605.07594
- https://arxiv.org/abs/2508.19828
- https://arxiv.org/abs/2601.03192
- https://github.com/mem0ai/mem0
- https://www.microsoft.com/en-us/security/blog/2026/06/22/guarding-ai-memory/

Vendor benchmark figures are vendor claims until independently reproduced for the
relevant workload. No framework is demonstrated to meet JARVIS's cross-turn
Hindi/Hinglish, privacy and *zero unsafe influence* acceptance conditions by default.

## Target architecture — two independent decisions, shared policy

**4.4 (background, off-voice-path):**

```text
accepted canonical USER turn
 -> existing deterministic source/secret/explicit-intent prefilter
 -> existing model-generated candidate proposal
 -> JARVIS structural policy
 -> optional isolated consolidation comparison (LangMem-style challenger)
 -> JARVIS dedupe/conflict/sensitivity reviewer
 -> session quarantine or pending owner review
 X  no automatic MemoryService write / SQLCipher mutation
```

**4.5E (only after later owner approval; now shadow-only):**

```text
current accepted owner turn + explicit task/state brief
 -> scoped task/needs identification (not free-text memory dump)
 -> JARVIS canonical eligibility + current temporal/source/sensitivity guards
 -> lexical/dense retrieval, if genuinely needed
 -> state-conditioned candidate comparison / optional JEV challenger
 -> independent memory-necessity & no-steering evaluation
 -> fixed budget, provenance tags, user-intent override
 X  no automatic ContextAssembler injection in this branch
```

New `decision_shadow.py` only produces disposition/reason *for evaluation*.
It intentionally **does not** return canonical values or provide a path to
`MemoryService` or `ContextAssembler`, and is not imported by production
voice code. A model's confidence never authorizes persistence or release.

## Experimental design and measurable gates

**A. Candidate extraction/consolidation:**
- Compare existing Phase-4.4 proposal/policy vs (separately) LangMem stateless
  manager; optionally a Hindsight isolated comparator. Hold model, consent,
  user text and domain samples constant across runs.
- Capture exact span grounding to a canonical accepted USER turn, proposal
  schema, stable durable vs transient vs hypothesis, corrections, changes vs
  retractions, conflict/dedup and provenance. Block quoted/tool/web claims and
  secrets **before** any provider call.
- Score proposal precision/recall, *false permanent-write candidates*,
  missed durable facts, duplicate proposals, temporal/conflict handling,
  privacy violations, provider call count and p50/p95 latency.
- Keep all proposals disposable and review-only. Any auto-admission proposal
  needs a **separate** design, approved narrow category, zero privacy/authority
  violations, blinded owner-machine acceptance and rollback/correction tests.

**B. Proactive context utility:**
- Compare (1) no memory, (2) already accepted retrieval as candidate generator
  with no injection, (3) typed task-scoped policy, (4) offline Hindsight/
  MemCompiler-inspired compilation, and (5) JEV if worth data/cost trade-offs.
- For each task, measure whether the candidate is ESSENTIAL, HELPFUL,
  UNNECESSARY or STEERING_RISK using independent labels, and whether including
  it improves an answer **versus no-memory baseline**. Do not rank on mere
  similarity or label-only quality.
- Include false relevancy, explicit negation, stale/superseded or forgotten
  memory, scope collisions, direct user contradiction, language shifts,
  adversarial memory-instruction injection and unsupported inferences.
- Require **zero observed unsafe influence on a completely new, independently
  curated holdout**, report finite-sample uncertainty, and satisfy predeclared
  nontrivial helpful/essential recall and latency/cost budgets. Zero observed
  failures is not mathematical proof of zero risk.
- English/Hindi/Hinglish and voice-endpoint behaviour must be separately
  stratified. Keep holdout private from implementers until final locked run;
  do not promote the synthetic test cases in this branch as blind acceptance.
- Prefer local source/metadata processing. No external PII to LangMem, JEV,
  Hindsight Cloud or any other model without explicit approved privacy scope.

**C. Operational/performance:**
- Test Windows 11 / Python 3.11, 16 GB RAM, RTX 5060 Ti 8 GB coexistence
  with existing vision/ASD/wake/audio; cold and warm p50/p95 and memory usage.
- Compare baseline to every addition; avoid added LLM calls on hot voice path.
- Fail closed and preserve existing assistant response when candidate
  classifier/provider is unavailable. Retain privacy/Authority/OPA gates,
  temporal deletion semantics and current-turn primacy.
- Require clean exact-head Ruff/pytest/Windows security CI and real owner
  machine observation before any status upgrade.

## Phase plan and authorization

1. **This PR: research + pure shadow contract/unit tests**, deliberately
   disconnected. No dependency installs, model downloads or credentials.
2. Separate benchmark PR with synthetic development sets and sealed *new*
   owner-held acceptance corpus; compare existing, LangMem, and optionally
   Hindsight; evaluate MemCompiler-style state conditioning as an algorithm,
   not an automatic vendor replacement.
3. Review empirical outcomes with owner; choose one narrow candidate for
   a default-OFF real runtime shadow (no memory values logged or released).
4. Only after independent blind and owner-machine acceptance, request new
   explicit approval for a scoped production rollout. **Do not merge**
   unvalidated 4.5E/4.4 implicit durable writing changes to `main`.

D8 and all automatic capability acquisition remain paused and out of scope.
