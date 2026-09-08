# Step 4 Phase 4.5D Final V2 Acceptance Result

Status: **FAIL_ACCEPTANCE — architecture rejected; evidence retired to development-only**

Owner run SHA: `7d9bc60bb37953ba1d6b45c7b46a136b1397203f`

Owner evidence file: `.step4-phase45d-final-v2-acceptance.json`

Owner evidence SHA-256: `bb718e2a7df71ea8b05b90e45b3aa0718643c1cf94323a03ae47a7a33d97bf0a`

The exact owner-run SHA passed all repository CI jobs (Ruff, pytest, Windows DPAPI, Windows Hello helper). The V2 evidence file was produced once on the accepted owner Windows `.venv` with CUDA and must not be overwritten or rerun for acceptance.

## Frozen V2 protocol actually run

- Qwen embedding: `Qwen/Qwen3-Embedding-0.6B`
  - revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
  - 256 dimensions
- first stage: eligible-current FTS5 + exact dense cosine + equal-weight RRF
- first-stage/reranker candidate window: 3
- Qwen reranker: `Qwen/Qwen3-Reranker-0.6B`
  - revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`
  - frozen JARVIS memory instruction
- independent verifier: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
  - revision `1427fd652930e4ba29e8149678df786c240d8825`
- confidence estimator: frozen `StandardScaler -> LogisticRegression`
- risk control: MAPIE `1.5.0`, precision target `0.95`, confidence `0.95`, split fixed-sequence testing
- corpus: 1,800 fresh synthetic cases
  - calibration: 600 release + 600 abstain
  - validation: 300 release + 300 abstain
- validation labels were not used for tuning.

## Acceptance outcome

MAPIE found no valid release threshold.

Validation checks:

- MAPIE valid threshold: **FAIL**
- positive Top-1 accuracy >= 0.85: **PASS**
- positive Recall@3 >= 0.90: **FAIL**
- zero false releases: **PASS** because no threshold released anything
- overall release recall >= 0.40: **FAIL** because no threshold was valid
- per-language release recall >= 0.25: **FAIL** because no threshold was valid
- zero security-boundary releases: **PASS** because no threshold released anything

Overall status: `FAIL_ACCEPTANCE`.

## Retrieval diagnosis — candidate starvation is confirmed

Calibration ranking:

- positive Top-1: `533/600 = 0.888333`
- positive Recall@3: `533/600 = 0.888333`

Validation ranking:

- positive Top-1: `266/300 = 0.886667`
- positive Recall@3: `266/300 = 0.886667`

The Top-1 and Recall@3 counts are exactly identical in both splits.

This is decisive evidence about the current architecture: whenever the expected memory entered the three-item candidate set, the Qwen reranker promoted it to rank 1. Every positive ranking miss was therefore a first-stage/candidate-window miss, not a Qwen reranker ordering error inside the available top three.

The current production research code asks `SemanticRetrievalService` for only three candidates and the Qwen reranker is also bounded to three. This is inconsistent with the mature retrieve-then-rerank pattern, where a cheap retriever normally generates a substantially wider shortlist and the CrossEncoder then reranks that shortlist.

### Language breakdown

Calibration positive ranking:

- EN: `195/200 = 0.975`
- HI: `150/200 = 0.750`
- Hinglish: `188/200 = 0.940`

Validation positive ranking:

- EN: `97/100 = 0.970`
- HI: `73/100 = 0.730`
- Hinglish: `96/100 = 0.960`

Hindi is the dominant retrieval weakness.

Validation Hindi relation-level Recall@3:

- branch: `10/10`
- channel: `10/10`
- editor: `7/10`
- format: `10/10`
- map: `9/10`
- region: `0/10`
- retention: `10/10`
- seat: `9/10`
- shell: `5/10`
- sync: `3/10`

The failure is therefore concentrated around particular cross-lingual relation semantics rather than being a general inability to retrieve Hindi queries.

## Confidence diagnosis — the frozen learned gate did not transfer

This is not merely a MAPIE power problem.

Across the 101 preregistered probability thresholds from `0.50` through `0.999`, **no threshold even achieved empirical 0.95 precision on V2 calibration**.

At the highest preregistered threshold, `0.999`:

- released: `105`
- true positives: `76`
- false positives: `29`
- empirical precision: `76/105 = 0.723810`
- positive release recall: `76/600 = 0.126667`

The best empirical precision among the preregistered thresholds was only about `0.736`.

MAPIE was therefore correct to return no valid threshold. Increasing calibration size or weakening multiple-testing correction would not rescue this frozen confidence model.

### Pathological high-confidence unsafe cases

At probability >= `0.999`, the 29 calibration false positives were dominated by:

- relation mismatch: 19
- ambiguous: 9
- near miss: 1

The frozen logistic model learned a **negative coefficient for reranker margin** (`-2.1205555`). On V2 this is harmful: many ambiguous/relation-mismatch cases have a high reranker score but a small top1-top2 margin, and the negative margin coefficient increases rather than decreases their predicted safety probability.

This is evidence of development-set correlation/transfer failure. The frozen logistic model must not be rescued by threshold tuning on V2.

## Independent verifier diagnosis — mMARCO is the wrong semantic contract for the final gate

The mMARCO verifier was useful on the retired 320-case development set, but V2 exposes a serious transfer problem.

On V2 calibration its raw score was highly discriminative, but validation changed the positive query phrasing and safe-pair scores shifted down sharply. Relation-mismatch, ambiguous, near-miss and absent queries remained high-scoring because mMARCO is fundamentally an information-retrieval passage-ranking model.

This matches the model's documented purpose: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` is trained on multilingual MS MARCO for query/passage ranking. JARVIS needs a stricter semantic contract: whether the already-eligible memory directly and sufficiently answers the exact requested fact/relation.

Therefore mMARCO is retired as the selected final confidence verifier. It may remain a development baseline only.

## Research-first implications

Current external guidance supports these conclusions:

1. Sentence Transformers' retrieve-and-rerank pattern retrieves a substantially wider candidate set (their documentation gives an example of about 100 candidates) before CrossEncoder reranking.
2. Qwen3-Embedding-0.6B supports Matryoshka output dimensions from 32 to 1024, so the existing 256d contract can be evaluated against 512/1024 as a secondary retrieval-quality variable without changing model family.
3. `BAAI/bge-reranker-v2-m3` is an Apache-2.0 multilingual reranker explicitly recommended by BAAI for multilingual/efficient reranking and is now justified for a development bake-off because V2 actually failed.
4. `mixedbread-ai/mxbai-rerank-base-v2` is another Apache-2.0 ~0.5B multilingual reranker with Sentence Transformers support and can be considered if BGE/Qwen evidence is insufficient.
5. The final release-confidence signal must be tested for semantic sufficiency/answerability, not merely retrieval relevance.

## Next development-only experiment

Do **not** create V3 yet.

First use exposed V2 only as retired development data to answer architecture questions cheaply:

### A. Retrieval depth diagnostic

Keep the accepted Qwen 0.6B model and 256d embedding unchanged initially.

Measure first-stage positive recall at candidate depths:

- 3
- 5
- 10
- 20
- 50
- 100 when practical

Then rerank the wider shortlist with Qwen and measure Top-1 by language/relation.

Because the correct candidate was always ranked first whenever present in the V2 top three, retrieval depth is the first variable to test.

### B. Embedding-dimension diagnostic only if depth is insufficient

If a wider 256d candidate pool does not clear the desired ranking floor, compare Qwen Matryoshka dimensions 256 vs 512 vs 1024 on the same retired V2 development data.

Do not change the canonical embedding contract until development evidence justifies it.

### C. Confidence/verifier bake-off

Retire the frozen V2 logistic/mMARCO architecture.

Use retired data only to compare stricter multilingual semantic-verification candidates, beginning with mature Apache-2.0 options. BGE reranker v2-m3 is now justified; other candidates should only be added when they provide a materially different, well-supported signal.

Any learned confidence model must avoid the demonstrated pathological transfer behavior. Probability calibration and final risk calibration must use data independent of model fitting.

## V3 rule

Only after the development bake-off selects and freezes a materially better architecture should a completely fresh V3 calibration/validation corpus be generated.

V2 calibration and validation are now fully exposed and may never again be used as acceptance evidence.

The frozen acceptance principles remain unchanged:

- precision target `0.95`
- confidence `0.95`
- overall release recall floor `0.40`
- each EN/HI/Hinglish release recall floor `0.25`
- strong ranking gates
- zero security-boundary releases
- validation never tunes the architecture
- canonical eligibility remains deterministic authority
- learned retrieval confidence never creates/modifies/resurrects canonical truth

Phase 4.5E remains blocked.
