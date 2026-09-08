# Step 4 Phase 4.5E — Deferred Closure

Date: 2026-09-08

## Status

**DELIBERATELY DEFERRED / NOT ACCEPTED — AUTOMATIC MEMORY INJECTION REMAINS DISABLED — STEP 4 RETURNS TO BOUNDED COMPLETE**

The owner has chosen not to let Phase 4.5E automatic memory influence block further JARVIS V1 development. This is a bounded fail-closed closure, not a claim that proactive semantic memory injection has been solved.

The already-accepted Step-4 foundation and provider-assisted 4.5D explicit recall remain production behavior. The unaccepted Phase-4.5E shadow/influence experiments are preserved as research evidence only and are not merged into protected `main`.

## Exact remaining problem

Phase 4.5E was investigating a different problem from explicit memory recall:

> During an ordinary user turn that does not explicitly invoke memory, when should a retrieved personal memory be allowed to influence the answer, and when would using that memory be unnecessary, stale, misleading, or steering?

Retrieval similarity is not sufficient authority for this decision. Current user input must continue to outrank passive memory.

## 4.5D -> 4.5E failure map

| Approach | Role tested | Result | Durable lesson |
| --- | --- | --- | --- |
| FTS5 + Qwen3 Embedding + RRF + Qwen3 Reranker | candidate retrieval/ranking | **ACCEPTED** for derived retrieval | Good at finding/ranking eligible memory; ranking does not authorize use. |
| Qwen reranker instruction selection | direct/sufficient answer relevance | **ACCEPTED only for reranking** | Better confidence ordering, but no release/influence authority. |
| Gemini/GLiClass semantic judge experiments | semantic answer sufficiency | **REJECTED as strict release authority** | Generic semantic judging did not meet the frozen precision/security boundary. |
| Multilingual NLI answerability guard (`mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`) | veto related-but-different explicit recall | **REJECTED** | It blocked all 10 correct source releases; meta-answerability was a poor task formulation. |
| Multilingual zero-shot answer-type guard using the same mDeBERTa family | current-value/current-comparison vs veto roles | **REJECTED standalone** | Kept 12/12 legitimate development allows but still produced two false allows. Useful only as evidence that a complementary veto can help. |
| GLiClass question-role models | 10-way multilingual question-role classification | **REJECTED / retired** | Both tested checkpoints collapsed to a single veto class and had 0 allow recall. |
| Frozen multilingual embeddings + LogisticRegression | task-specific local guard | **REJECTED / retired** | Every candidate produced multiple unsafe false allows; model hopping among frozen encoders did not solve the boundary. |
| Provider + local-guard V4 composite | explicit recall release consensus | **REJECTED** | Zero provider-backed false releases but unacceptable recall; provider-independent core also produced a Hinglish negation false release. |
| Same-provider structured 4.5D fallback | explicit `recall_memory` | **OWNER-ACCEPTED bounded compromise** | Structured selection + deterministic canonical reconstruction + exact lookup + second semantic verification gives useful explicit recall while failing closed. |
| 4.5E.1 local Qwen shadow retrieval | ordinary conversation candidate observation | **FUNCTIONAL OWNER PASS; RESOURCE GATE DEFERRED; NOT ACCEPTED** | Correct direct memories ranked first and unrelated turns still returned candidates, proving relevance != permission to influence. |
| 4.5E.2 Qwen three-prompt ESSENTIAL/HELPFUL/STEERING classifier | proactive memory influence utility gate | **REJECTED** | Multilingual holdout had 0 ESSENTIAL recall, 0 HELPFUL recall, four unsafe false influences, and highly collinear score channels. Reranker logits are not a policy classifier. |

The detailed historical 4.5D documents and their exposed corpora remain authoritative research evidence and must not be reused as fresh acceptance data.

## Phase 4.5E.1 evidence and disposition

Research branch:

- `implementation/step-4-phase45e-context-injection`
- implementation head used for owner functional testing: `62b9fc082438b153d770ba65d6bcf45018840aa7`

Observed on the owner Windows / RTX 5060 Ti runtime:

- process-local Qwen embedding/reranking models loaded successfully;
- accepted USER turns triggered asynchronous shadow retrieval;
- direct test memories ranked first for color, vehicle, and city questions;
- existing derived embeddings were reused after initial creation;
- ordinary unrelated/advice turns still produced top-3 candidates;
- shadow logs exposed opaque assertion IDs rather than raw values;
- every observation remained `context_injection=False`;
- the conversation continued independently of the shadow path.

The owner deliberately deferred the final CPU/GPU/resource-profile acceptance gate. Therefore 4.5E.1 is **not accepted production architecture** and its runtime/config changes must not enter `main` through this closure.

## Phase 4.5E.2 evidence and disposition

Research branch result head:

- `implementation/step-4-phase45e2-utility-gate`
- result commit: `677badddbba8d7739344d849f891158e6bd6f566`

The fresh 64-case ESSENTIAL / HELPFUL / UNNECESSARY / STEERING_RISK experiment used English calibration and a frozen Hinglish/Hindi holdout. The proposed three Qwen reranker prompt scores were rejected because the holdout produced:

- ESSENTIAL recall: `0.0`;
- HELPFUL recall: `0.0`;
- unsafe false influences: `4`;
- STEERING_RISK recall: `0.875`;
- macro F1: approximately `0.234`.

The unsafe false influences included deliberate lexical/semantic collisions such as Snowflake clustering paired with a remembered snow-boot size and a falcon-bird question paired with a remembered vehicle named Falcon.

Performance was not the blocker; semantic safety/utility separation was.

The exposed 4.5E.2 multilingual holdout is retired for future model selection.

## Fresh 2026 research conclusion after the rejection

A final research pass was performed before closing the investigation rather than immediately trying another classifier.

Current external evidence reinforces the decision to defer:

1. Microsoft Security, **Guarding AI memory** (2026-06-22) treats retrieval itself as a risk decision and recommends deterministic boundaries outside the model plus re-evaluation of retrieved memory for relevance, freshness, and tampering before use.
   - https://www.microsoft.com/en-us/security/blog/2026/06/22/guarding-ai-memory/
2. Microsoft Learn, **AI Memory / Context Poisoning** (updated 2026-08-01) describes persistent memory/grounding stores as a durable attack surface and recommends schema-bound storage, access control, sanitization, versioning/rollback, and trust controls.
   - https://learn.microsoft.com/en-us/security/zero-trust/catalog-ai-attack-techniques/ai-memory-context-poisoning
3. OWASP GenAI, **Memory Is a Feature. It Is Also an Attack Surface** (2026-05-13) documents persistent-context poisoning as an agentic security problem: remembered content can influence future reasoning long after the original interaction.
   - https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/
4. Microsoft Research, **MemCompiler: Compile, Don’t Inject — State-Conditioned Memory for Embodied Agents** (2026-05) reports that static monolithic memory injection can become misaligned with evolving state and can degrade some executors below a no-memory baseline; it proposes state-conditioned selection/compilation instead.
   - https://www.microsoft.com/en-us/research/publication/memcompiler-compile-dont-inject-state-conditioned-memory-for-embodied-agents/
5. **Context Awareness Gate for Retrieval Augmented Generation** reports that irrelevant retrieved context can materially degrade generation quality and motivates an explicit context-use gate rather than unconditional retrieval injection.
   - https://arxiv.org/abs/2411.16133

These sources support the architecture principle already observed on the owner machine: finding a semantically related memory is materially easier than proving that it should influence an ordinary answer.

No mature drop-in component found in this pass cleanly satisfies JARVIS's multilingual, privacy, lifecycle, steering, and zero-false-influence requirements without another substantial task-specific research program. Repeating previously rejected NLI/zero-shot/reranker model families would be model hopping rather than research-first engineering.

## Closure decision

Phase 4.5E is deliberately deferred.

Production state remains:

```text
explicit governed remember/inspect/correct/forget       ACCEPTED
4.5A-4.5C derived local retrieval/reranking             ACCEPTED
provider-assisted explicit recall_memory                ACCEPTED when configured
strict independent 4.5D verifier                        DEFERRED / UNRESOLVED
4.5E ordinary-conversation shadow runtime               RESEARCH ONLY / NOT MERGED
4.5E proactive memory influence gate                    REJECTED / DEFERRED
automatic ContextAssembler semantic memory injection    DISABLED / NOT ACCEPTED
```

No threshold is relaxed and no failed learned component is promoted merely to finish Step 4.

## Branch disposition

Do **not** merge the stacked experimental Phase-4.5E branches into protected `main` as production implementation. Git history remains the archive for their code/harnesses.

This docs-only closure is based from the accepted protected-main Step-4 state so moving forward does not accidentally import unaccepted shadow-runtime changes.

## Revisit conditions

Reopen automatic memory influence only when there is a materially new reason to expect success, for example:

- a mature context/memory utility component with strong multilingual abstention and steering resistance;
- a later Step-6 truthfulness/evidence architecture that can provide a better support/necessity boundary;
- a later Step-7 governed capability contract that makes memory use explicit and structured rather than passive free-text injection;
- a state-conditioned/context-compilation architecture demonstrated to fit JARVIS without weakening deterministic lifecycle/security rules;
- a task-specific training program worth the engineering/data cost after higher-value roadmap capabilities are complete.

Any future acceptance must use a completely fresh never-exposed corpus.

## Next roadmap state

The owner has now explicitly authorized moving forward. Step 4 remains **DONE (BOUNDED)** and Step 5 — **Local/Offline Survival and Provider Resilience (CAP-048, CAP-049)** — becomes the active lifecycle at **REQUIREMENTS / RESEARCH**.
