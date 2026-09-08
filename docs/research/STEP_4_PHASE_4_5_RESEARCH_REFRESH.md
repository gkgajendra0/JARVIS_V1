# Step 4 — Phase 4.5 Semantic Retrieval Research Refresh

Date: 2026-09-05

## Status

**RESEARCH REFRESH COMPLETE — IMPLEMENTATION SELECTION REQUIRES A NARROW LOCAL BAKE-OFF.**

Phase 4.5 must add semantic retrieval over already-canonical eligible memory without allowing retrieval scores, embeddings, rerankers, indexes, or model output to establish or mutate truth.

The earlier JARVIS retrieval research remains valuable because it was measured on the actual Windows/RTX machine. This refresh checks whether newer mature technology changes the selected implementation path before production code begins.

---

## 1. Existing measured incumbent

The earlier owner-machine retrieval research selected:

- SQLite/SQLCipher canonical store;
- FTS5 lexical retrieval;
- `Qwen/Qwen3-Embedding-0.6B`;
- 256-dimensional Matryoshka embeddings;
- JARVIS-specific English query instruction;
- equal-weight reciprocal-rank fusion;
- top-3 `Qwen/Qwen3-Reranker-0.6B`;
- BF16 reranking;
- deterministic tie-break by fused rank then stable memory ID;
- no dedicated vector database;
- no arbitrary abstention threshold.

Measured on the actual JARVIS RTX 5060 Ti research machine, the earlier Qwen configuration achieved:

- embedding Recall@1: 0.8824;
- embedding Recall@3: 1.0000;
- RRF Recall@1: 0.9412;
- RRF Recall@3: 1.0000;
- top-3 reranked Recall@1/3 and MRR: 1.0000;
- Qwen embedding query encode p50 about 63 ms;
- embedding peak CUDA allocation about 1.29 GB decimal;
- combined embedding + reranker peak CUDA allocation about 2.35 GiB in the original harness.

This is the incumbent and must not be displaced by generic benchmark marketing alone.

Existing record:

- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`

---

## 2. Current inference library — Sentence Transformers

Current PyPI evidence shows `sentence-transformers` 6.0.x is production/stable, supports Python 3.11, and directly supports modern embedding and CrossEncoder/reranker architectures.

The current Sentence Transformers documentation explicitly demonstrates:

- `SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")` style embedding use through the model's published Sentence Transformers integration;
- `CrossEncoder("Qwen/Qwen3-Reranker-0.6B")` for Qwen causal-LM reranking through the current modular `Transformer + LogitScore` CrossEncoder architecture;
- normal retrieve-then-rerank usage where the slower CrossEncoder is applied only to a small first-stage candidate set.

Disposition: **use Sentence Transformers as the preferred mature local inference boundary rather than building custom tokenizer/pooling/reranker inference.**

Current references:

- https://pypi.org/project/sentence-transformers/
- https://www.sbert.net/docs/cross_encoder/usage/usage.html
- https://www.sbert.net/docs/cross_encoder/usage/custom_models.html
- https://www.sbert.net/docs/package_reference/cross_encoder/model.html

---

## 3. Incumbent embedding candidate — Qwen3-Embedding-0.6B

Current Qwen model-card evidence still makes this a strong JARVIS fit:

- 0.6B parameters;
- Apache-2.0 license;
- 100+ languages;
- 32k context;
- up to 1024 dimensions;
- Matryoshka output dimensions from 32 to 1024;
- instruction-aware retrieval;
- official Sentence Transformers integration;
- cosine similarity configuration;
- Qwen recommends task-specific instructions and notes 1–5% typical gains from instructions.

The Qwen card reports strong multilingual retrieval/ranking performance and the previous JARVIS-specific benchmark already proved 256d + instruction works well on the actual machine.

Disposition: **MEASURED INCUMBENT; RETAIN IN BAKE-OFF.**

References:

- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/blob/main/README.md
- https://github.com/QwenLM/Qwen3-Embedding
- https://qwenlm.github.io/blog/qwen3-embedding/

---

## 4. New challenger — EmbeddingGemma 300M

Google DeepMind now positions EmbeddingGemma as a best-in-class on-device multilingual embedding model under 500M parameters.

Current official evidence:

- about 308M parameters;
- trained across 100+ languages;
- designed specifically for on-device semantic search/RAG;
- 2k input context;
- Matryoshka output dimensions from 768 down to 128;
- can run under 200 MB RAM when quantized according to Google;
- offline/local use keeps embedding generation on device;
- official Sentence Transformers inference documentation exists;
- current research reports state-of-the-art performance for its size and competitiveness with substantially larger models.

Trade-offs relative to Qwen:

- smaller model and potentially materially lower runtime footprint;
- 2k context instead of Qwen's 32k, which is still far above the expected length of canonical JARVIS memory assertions;
- Gemma terms/model-access workflow rather than Qwen's Apache-2.0 frictionless license;
- Hugging Face access may require accepting the model terms and using a token;
- no prior JARVIS-specific owner-machine measurement yet.

Disposition: **ADD AS THE ONLY NEW EMBEDDING CHALLENGER.**

Do not broaden the bake-off to many embedding models. BGE-M3 was already measured in the earlier JARVIS research and lost the overall GPU/Recall@3 trade-off to Qwen.

References:

- https://deepmind.google/models/gemma/embeddinggemma/
- https://ai.google.dev/gemma/docs/embeddinggemma
- https://ai.google.dev/gemma/docs/embeddinggemma/model_card
- https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers
- https://deepmind.google/research/publications/194199/

---

## 5. Reranker refresh — Qwen3-Reranker-0.6B remains the incumbent

Current Qwen and Sentence Transformers support is stronger than during the earlier research:

- Qwen3-Reranker-0.6B remains a 0.6B, 100+ language, 32k-context reranker;
- Qwen publishes strong multilingual reranking results;
- current Sentence Transformers directly loads it as `CrossEncoder("Qwen/Qwen3-Reranker-0.6B")` and handles the causal-LM true/false logit scoring through its modular CrossEncoder implementation.

The earlier JARVIS top-3 reranker measurement already produced perfect ordering on the fixed corpus.

However, Phase 4.5 should not assume a reranker is mandatory if a newer/smaller first-stage stack can achieve the required measured result without it.

Disposition:

1. benchmark lexical + dense + RRF first;
2. add Qwen3-Reranker-0.6B only when the fixed JARVIS corpus contains first-stage ordering errors that reranking materially fixes;
3. keep the reranker window small (incumbent top 3) unless new data proves another window is better;
4. do not select a reranker-score abstention threshold before dedicated calibration.

References:

- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://www.sbert.net/docs/cross_encoder/usage/custom_models.html
- https://www.sbert.net/docs/cross_encoder/usage/usage.html

---

## 6. Vector storage/search refresh

### sqlite-vec

`sqlite-vec` remains attractive as a tiny cross-platform SQLite vector extension, but its own project still warns that it is pre-v1 and breaking changes should be expected. The latest stable release observed in this refresh is 0.1.9, while 0.1.10 remains alpha/pre-release. Current Windows packaging issues also exist in the issue tracker.

Disposition: **DO NOT ADD TO THE Phase-4.5 base implementation.**

References:

- https://github.com/asg017/sqlite-vec
- https://github.com/asg017/sqlite-vec/releases

### SQLite-Vector (`sqliteai/sqlite-vector`)

A more mature current alternative now exists:

- `sqliteai/sqlite-vector` reached 1.0.0 on 2026-05-25;
- published Windows x86_64 binaries/Python packaging exist;
- vectors are stored as ordinary table BLOBs rather than requiring a virtual-table canonical owner;
- exact/SIMD and quantized search paths are available;
- it is designed for offline edge/local use.

This makes SQLite-Vector the preferred **future extension candidate** if JARVIS later proves that Python-side exact cosine scanning is a real bottleneck.

However, no current JARVIS scale measurement justifies adding another native extension to the already-pinned SQLCipher Windows runtime. Loadable-extension compatibility, lifecycle/forget semantics and reproducible packaging would need owner-machine validation first.

Disposition: **DO NOT ADD YET; ESCALATION CANDIDATE ONLY AFTER SCALE EVIDENCE.**

References:

- https://github.com/sqliteai/sqlite-vector
- https://github.com/sqliteai/sqlite-vector/releases

---

## 7. Base vector-search implementation strategy

For the initial Phase-4.5 implementation, prefer the smallest auditable path:

```text
SQLCipher canonical eligible rows
 -> derived embedding table / rebuildable BLOB representation
 -> normalized local embeddings
 -> bounded exact cosine similarity over eligible vectors
```

The exact implementation may use mature NumPy/PyTorch tensor operations supplied by the selected Sentence Transformers stack. Do not build an ANN index before a corpus-scale benchmark proves it is necessary.

Why:

- canonical personal memory is expected to be far smaller than internet-scale retrieval corpora;
- 256-dimensional Matryoshka vectors are compact;
- an exact scan has deterministic recall and simple physical-forget/rebuild semantics;
- adding a native vector extension now increases SQLCipher/Windows packaging and lifecycle surface without measured benefit.

A dedicated vector extension remains a reversible optimization, not canonical architecture.

---

## 8. Cloud embeddings are not the default retrieval path

The current one-provider rule would technically permit a Gemini embedding model because Gemini is the active production provider. That does not make cloud embeddings the preferred personal-memory retrieval design.

Phase 4.5 prioritizes local embedding/reranking because:

- canonical personal memory can contain private data;
- retrieval should continue to work offline;
- existing local models already meet the capability class;
- repeated query embeddings should not require cloud round trips when local inference is sufficient;
- no second paid AI provider is needed.

Disposition: **LOCAL FIRST. No cloud embedding dependency for the base Phase-4.5 implementation.**

---

## 9. Narrow bake-off required before implementation selection

Do not rerun a broad model zoo.

Compare exactly:

### A — measured incumbent

- `Qwen/Qwen3-Embedding-0.6B`;
- 256 dimensions;
- existing JARVIS retrieval instruction;
- Sentence Transformers current stable runtime.

### B — new efficiency challenger

- `google/embeddinggemma-300m`;
- 256 dimensions if supported by the selected runtime path;
- task-appropriate retrieval prompt/prefix per Google's model guidance;
- Sentence Transformers current stable runtime.

Use the same fixed JARVIS multilingual retrieval corpus and the same deterministic eligibility/FTS/RRF logic.

Measure at minimum:

- Recall@1;
- Recall@3;
- MRR;
- English/Hindi/Hinglish breakdown;
- absent-answer candidate behavior;
- query encode p50/p95;
- cold model load time;
- GPU allocation / process memory;
- derived vector size;
- first-stage hybrid end-to-end latency.

Then:

1. if EmbeddingGemma materially reduces resource use while meeting or exceeding the required retrieval quality, select it;
2. otherwise retain the already-measured Qwen incumbent;
3. only add the Qwen reranker if first-stage RRF still has meaningful ordering errors;
4. do not introduce sqlite-vector/sqlite-vec unless exact-scan scale measurements fail an evidence-based latency requirement.

---

## 10. Abstention remains unselected

No semantic score cutoff is approved yet.

The earlier corpus already showed that reranker logits cannot be treated as a universal confidence probability. Phase 4.5 must expand the acceptance corpus with:

- no-answer queries;
- ambiguous questions;
- near-miss distractors;
- stale/superseded memory;
- corrected memory;
- forgotten memory;
- sensitive/local-only memory;
- poisoned/non-owner content;
- English/Hindi/Hinglish paraphrases.

A retrieval abstention policy must be calibrated from this data rather than guessed.

---

## 11. Permanent authority/lifecycle rules

Semantic retrieval may rank only records that deterministic JARVIS policy already considers eligible.

It may never override:

- explicit owner correction or forget;
- canonical/source authority;
- valid/system-time semantics;
- sensitivity/release policy;
- supersession/retraction/deletion state;
- `MemoryService` mutation ownership;
- `ContextAssembler` release ownership.

Embeddings, fused ranks, reranker scores and vector indexes are all **derived/rebuildable evidence**, never canonical truth.

Physical forget must remove or invalidate all derived representations before the forgotten assertion can ever be returned again.

---

## Research disposition

The earlier architecture remains directionally correct, but one new efficiency challenger deserves measurement before implementation is frozen.

**Phase-4.5 next action:** build a research-only, fixed-corpus local bake-off for Qwen3-Embedding-0.6B versus EmbeddingGemma 300M under the current Sentence Transformers runtime, keeping FTS5/eligibility/RRF identical. Do not add a vector extension or production retrieval code until that result is measured.
