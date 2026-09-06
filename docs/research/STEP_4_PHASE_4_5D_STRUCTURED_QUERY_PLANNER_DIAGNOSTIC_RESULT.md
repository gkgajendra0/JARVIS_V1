# Step 4 Phase 4.5D — Structured Query Planner Development Diagnostic Result

## Status

**Development diagnostic complete. Continuation gates failed. Not acceptance evidence. Phase 4.5E remains blocked.**

Owner run candidate:

- branch: `implementation/step-4-memory-context`
- SHA: `b264a7141e3843dabcff5d1c964f08dcd909a371`
- output: `.step4-phase45d-v2-structured-query-planner-diagnostic-v1.json`
- provider/model: Gemini `gemini-3.5-flash-lite`
- request shape: one user query per request
- request pace: 12 RPM
- Qwen embedding/reranker: not invoked
- corpus: exposed/retired V2 validation queries only

This result is architecture-development evidence only. It cannot authorize V3 acceptance or Phase 4.5E.

## Result summary

The frozen 45-case diagnostic produced:

| Metric | Result |
| --- | ---: |
| Cases | 45 |
| Diagnostic target releases | 12 |
| Diagnostic target abstains | 33 |
| Exact true releases | 10 |
| False/wrong releases | 6 |
| Missed target releases | 2 |
| True abstains | 27 |
| Precision | 0.625 |
| Target release recall | 0.833333 |
| Direct exact releases | 8/9 |
| Relation-comparison exact releases | 2/3 |
| Security-boundary releases | 0 |

Per-language target-release recall:

- English: 4/4 = 1.00
- Hindi: 3/4 = 0.75
- Hinglish: 3/4 = 0.75

The architecture therefore failed the frozen continuation gates because it produced ordinary-semantic false releases and missed one of three relation-comparison targets.

## What worked

### Deterministic security boundaries remained intact

There were **zero releases** from:

- historical
- forgotten
- local-only
- secret
- untrusted

This is important evidence that the canonical eligibility/lifecycle boundary and exact-facet evidence gate are doing their intended job. The learned interpreter did not resurrect forbidden or unavailable canonical memory.

### Exact structured lookup removed the old retrieval problem

The exact-facet path did not invoke Qwen embedding or reranking and still released 10 of 12 intended canonical facts. There were no wrong-memory releases among diagnostic target-release rows.

This supports retaining the structured-query architecture rather than returning to free-text top-k retrieval for ordinary exact current facts.

### English question focus was clean in this sample

All four English target-release cells were exact, while the demonstrated ordinary-semantic false releases occurred only in Hindi/Hinglish.

## Failure analysis

The six false releases are concentrated in four semantic answer-type classes:

| Case | Language | Category | What the frozen query asks for |
| --- | --- | --- | --- |
| `v2_val_a0026` | Hindi | near_miss | why the recorded value was chosen |
| `v2_val_a0027` | Hinglish | near_miss | why the recorded value was chosen |
| `v2_val_a0078` | Hinglish | adversarial_lexical | which approval ticket was created after setting it |
| `v2_val_a0101` | Hindi | negation | which value replaced the rejected value |
| `v2_val_a0102` | Hinglish | negation | which value replaced the rejected value |
| `v2_val_a0153` | Hinglish | unsupported_source | who recommended the value |

These are not retrieval mistakes. In each case Gemini proposed an exact-current-fact path even though the actual requested answer is a **reason, related ticket/event, replacement/successor value, or recommender/provenance actor**.

The demonstrated weakness is therefore **question focus / requested answer type**, especially in Hindi and Romanized Hindi/Hinglish.

The two legitimate lookup misses were:

- `v2_val_p0093`: Hinglish direct current-fact query; final reason `incomplete_exact_fact_query`
- `v2_val_a0128`: Hindi relation-comparison query; final reason `incomplete_exact_fact_query`

Those misses are recall problems in proposal completeness, separate from the six false-release precision problems.

## Why no hand-written Hindi/Hinglish keyword patch is authorized

The frozen method explicitly requires mature-solution research before adding a custom lexicon/parser after an ordinary-semantic false release.

Adding rules for words such as `kyun`, `kisne`, `reject`, `replace`, `approval`, or their Devanagari equivalents would be brittle, language-specific, and likely to accumulate exceptions. It would also move JARVIS away from the provider-independent semantic architecture.

## Research decision after the failure

The next smallest task-matched experiment is an **independent multilingual NLI release guard** over only the already-released structured-query rows.

Selected mature candidate for development evaluation:

- model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- immutable revision: `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- task: natural language inference / multilingual zero-shot classification
- size: ~0.3B parameters, ~558 MB safetensors weights
- license: MIT
- training: XNLI plus multilingual-NLI-26lang-2mil7; more than 2.7M multilingual NLI pairs, with Hindi explicitly included

The model card also documents cross-lingual premise/hypothesis training, including English hypotheses paired with non-English premises. That makes a fixed English policy hypothesis a reasonable research fit for Hindi/Hinglish queries without training a custom classifier.

The proposed NLI question is intentionally narrower than the rejected free-text document verifiers:

> Can this user question be answered solely by the current canonical value of the selected relation for the selected subject?

Examples of intended behavior:

- direct current value lookup -> entail
- value/relation comparison -> entail
- why chosen -> neutral/contradict
- who recommended -> neutral/contradict
- replacement after rejection -> neutral/contradict
- approval ticket after setting -> neutral/contradict

The NLI model receives the **user query plus the already-grounded proposal surface references**, not canonical memory values and not the retrieved document. It has no release authority. A future production guard would only be allowed to veto an otherwise releasable exact-facet plan; it could never create or select canonical truth.

## Why MuRIL is not selected first

Google MuRIL is specifically pretrained on Indian languages and transliterated counterparts, which is attractive for Hinglish. However, the released base model is a pretrained encoder rather than a ready-made NLI/answer-type classifier for this task. Using it here would require custom supervised fine-tuning and a new labeled dataset.

Research-first policy therefore favors the ready-made multilingual NLI model before building a MuRIL classifier ourselves.

## Next diagnostic constraints

The next diagnostic must:

1. consume the completed structured-query planner artifact rather than rerun Gemini;
2. evaluate only rows that the current structured path released;
3. reconstruct query text transiently from the frozen V2 generator by case ID;
4. never persist query text, hypothesis text, canonical values, or memory text;
5. use the pinned mDeBERTa revision without changing Torch/Torchvision;
6. report raw entailment/neutral/contradiction probabilities so no owner rerun is needed for later offline threshold inspection;
7. use an untuned primary decision rule (NLI argmax = entailment) for the first development read;
8. remain development-only and leave Phase 4.5E blocked.

## Latency note

The planner artifact reports request latency around 5 seconds (`p50 ~= 5.003 s`, `p95 ~= 5.109 s`). This value is **not a clean provider latency measurement** because the harness starts timing before the shared 12 RPM pacer wait. After the first request, the deliberate five-second spacing dominates the metric.

Do not use this diagnostic latency field for production latency conclusions.

## Decision

- structured exact-facet architecture: **retain as development direction**
- current Gemini-only query interpreter: **insufficient by itself**
- deterministic security/eligibility boundary: **retained**
- hand-written Hindi/Hinglish lexicon patch: **rejected as next step**
- local multilingual NLI question-focus guard: **authorized for a small development diagnostic**
- fresh V3 acceptance: **not authorized**
- Phase 4.5E: **blocked**
