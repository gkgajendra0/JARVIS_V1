# Step 4 Phase 4.5E.2 — Memory Utility / Steering Gate Research

## Status

**RESEARCH + BAKE-OFF HARNESS ACTIVE ON STACKED BRANCH — NO MEMORY INJECTION**

Date: 2026-09-08

Branch: `implementation/step-4-phase45e2-utility-gate`

This branch is intentionally stacked on Phase 4.5E.1 head
`62b9fc082438b153d770ba65d6bcf45018840aa7`.

The owner chose to defer the remaining Phase 4.5E.1 CPU/GPU resource-profile gate so
development can continue. That gate is **not waived** and Phase 4.5E.1 is not yet
recorded as fully accepted. The owner-machine functional shadow run passed and is
sufficient to begin research-only Phase 4.5E.2 measurement. Production context
injection remains disabled.

## Problem confirmed by owner-machine evidence

Phase 4.5E.1 proved that the accepted local retrieval stack can rank the intended
memory first for direct personal questions. It also proved that retrieval alone
cannot authorize context injection: with three eligible memories and `top_k=3`,
unrelated questions still receive three ranked candidates.

Therefore the next decision is not "which memory is nearest?" but:

> Should this already-eligible current memory influence this answer at all?

A rank, cosine score, RRF score, or generic reranker logit cannot answer that authority
question by itself.

## Fresh research findings

### 1. Reuse the already-loaded Qwen3 reranker before adding another model

Qwen's current Qwen3-Reranker model card and SentenceTransformers integration support
task-specific instructions through `CrossEncoder(..., prompts=...)` and per-call
`predict(..., prompt=...)`.

Sources:

- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://www.sbert.net/docs/package_reference/cross_encoder/model.html

This is high leverage for JARVIS because Phase 4.5C already accepted
`Qwen/Qwen3-Reranker-0.6B` on the owner RTX 5060 Ti. A second task prompt can be
measured without loading another model copy. Qwen also recommends tailored English
instructions for task-specific and multilingual use.

### 2. Retrieval must be treated as a risk decision, not an automatic trust grant

Microsoft's June 2026 memory-security guidance explicitly recommends re-evaluating
retrieved memory for relevance, freshness, and tampering before use, and enforcing
memory boundaries outside the model.

Sources:

- https://www.microsoft.com/en-us/security/blog/2026/06/22/guarding-ai-memory/
- https://learn.microsoft.com/en-us/security/zero-trust/catalog-ai-attack-techniques/ai-memory-context-poisoning

This matches JARVIS's existing rule that canonical eligibility, sensitivity,
lifecycle, provenance, and conflict handling remain deterministic and upstream of
learned semantic work.

### 3. Memory poisoning and recommendation steering are current real-world risks

OWASP ASI06 and Microsoft's 2026 red-team/recommendation-poisoning work show that
persistent memory can create delayed steering across sessions. A memory may be true
or explicitly stored yet still be inappropriate to inject into an objective,
evidence-based, safety, or recommendation answer.

Sources:

- https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/
- https://www.microsoft.com/en-us/security/blog/2026/02/10/ai-recommendation-poisoning/
- https://www.microsoft.com/en-us/security/blog/2026/06/04/updating-taxonomy-failure-modes-agentic-ai-systems-year-red-teaming-taught-us/

Recent research also demonstrates persistent-memory poisoning as a distinct
multi-session attack surface:

- https://arxiv.org/abs/2605.15338
- https://arxiv.org/abs/2606.12703

The practical conclusion for JARVIS is conservative: similarity may nominate a
candidate, but an influence gate must be precision-first and uncertain means no
injection.

## Technology decision for the first 4.5E.2 bake-off

**ADAPT the accepted Qwen3 reranker with decomposed task-specific prompts.**

Do not add Mem0, LangMem, Graphiti, LlamaIndex, another vector database, another
retrieval framework, or a second GPU model for this first bake-off. Those systems
address storage/search/orchestration and do not provide the JARVIS-specific influence
authority boundary.

The first candidate uses one process-loaded Qwen reranker and three binary
instruction-aware scores:

1. **essential score** — is the memory necessary to answer the personal query
   correctly?
2. **helpful score** — is the memory safely useful for personalization without being
   necessary?
3. **steering score** — could the memory bias, override, or narrow the answer beyond
   the current user intent?

The model remains a semantic measurement component. It does not establish canonical
truth, mutate memory, or authorize provider context.

## Evaluation labels

The fresh 4.5E.2 corpus uses four labels:

- `ESSENTIAL` — without the memory JARVIS would need to guess or omit the requested
  personal fact;
- `HELPFUL` — safe personalization that materially improves the answer but is not
  required;
- `UNNECESSARY` — unrelated, redundant, or merely lexical/semantic adjacency;
- `STEERING_RISK` — allowing the memory to influence the answer could improperly bias
  an objective/factual/safety/recommendation response.

These cases are newly written for 4.5E.2 and do not reuse retired 4.5D corpora.

## Holdout design

The initial corpus contains 64 balanced cases:

- 16 `ESSENTIAL`;
- 16 `HELPFUL`;
- 16 `UNNECESSARY`;
- 16 `STEERING_RISK`.

For each label:

- cases `01`–`08` are English **calibration**;
- cases `09`–`16` are Hinglish/Hindi **holdout**.

Thresholds are selected only on calibration and are then frozen for holdout. This is
intentional because Qwen recommends English task instructions while JARVIS must work
with multilingual user turns.

## Threshold-selection rule

No numeric threshold is accepted in advance.

The harness derives candidate threshold tuples from observed calibration score
boundaries and chooses lexicographically:

1. minimize unsafe false influence (`UNNECESSARY` or `STEERING_RISK` classified as
   `ESSENTIAL`/`HELPFUL`);
2. minimize missed `STEERING_RISK`;
3. maximize `ESSENTIAL` recall;
4. maximize `HELPFUL` recall;
5. maximize macro F1.

The resulting threshold tuple is only a **measured candidate**. It is not a production
release rule. Holdout behavior, especially false influence, decides whether this
technology deserves further work.

## Deterministic boundaries remain outside the model

Phase 4.5E.2 does not replace existing deterministic controls:

- cloud-context eligibility before learned ranking;
- `local_only` / prohibited sensitivity exclusion;
- exact current canonical record ownership;
- lifecycle state and conflict handling;
- owner-explicit provenance;
- no model writes or resurrection;
- no ContextAssembler mutation.

Instruction-like/authority-seeking content is treated as a steering/security problem,
but this research does not falsely claim a language-model prompt is a deterministic
security boundary. Any later production design must either encode a deterministic
fact-only representation/allow shape or keep instruction-risk handling as a
conservative veto in addition to provenance controls.

## Research-only harness

Files:

- `tools/research/step4_phase45e2_utility_corpus.json`
- `tools/research/step4_phase45e2_qwen_utility_bakeoff.py`

The harness:

- loads the revision-pinned accepted Qwen3 reranker once;
- scores the same query/memory pairs with three per-call task prompts;
- calibrates only on the English split;
- freezes thresholds and evaluates Hinglish/Hindi holdout;
- reports confusion matrices, per-label precision/recall/F1, false influence,
  missed steering, raw case scores, latency, model load time, and peak CUDA
  allocation;
- prints `MEASURE_ONLY`;
- never opens the JARVIS memory database;
- never mutates provider context;
- never creates a production injection path.

## Decision gate after the bake-off

The next step is an owner-GPU run of the research harness.

Do **not** implement Phase 4.5E.3 injection from this branch. If the holdout shows
meaningful false influence or missed steering, research/tune or reject this candidate
before production integration. If it is strong, the next E.2 slice can adapt the
measured gate into shadow runtime only and collect ordinary-conversation evidence.

The deferred Phase 4.5E.1 CPU/GPU profile remains an open acceptance item and must be
completed before Phase 4.5E.1 is finally closed.
