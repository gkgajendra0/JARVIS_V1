# Step 4 — Hybrid RRF Retrieval Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — NOT FINAL PRODUCTION APPROVAL.**

Date: 2026-09-04  
Machine: actual JARVIS Windows machine  
Model: `Qwen/Qwen3-Embedding-0.6B`  
Semantic configuration: JARVIS-specific prompt, 256-dimensional Matryoshka output  
Lexical retrieval: SQLite FTS5  
Fusion: equal-weight Reciprocal Rank Fusion (RRF), rank constant 60, FTS window 10

## Result

The owner-machine run completed with `status = PASS`.

| Retrieval method | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| FTS5 | 0.6471 | 0.7647 | 0.7275 |
| Qwen JARVIS 256 | 0.8824 | 1.0000 | 0.9412 |
| Equal-weight RRF hybrid | **0.9412** | **1.0000** | **0.9608** |

Measured hybrid latency:

- FTS5 p50: 0.6272 ms
- FTS5 p95: 1.1573 ms
- Qwen encode p50: 60.9254 ms
- Qwen encode p95: 66.2976 ms
- end-to-end hybrid p50: **61.6144 ms**
- end-to-end hybrid p95: **66.9561 ms**
- peak CUDA allocation: **1,292,429,824 bytes (~1.29 GB)**

The extra fusion/lexical work added less than one millisecond to the median end-to-end path relative to the semantic embedding path.

## What equal RRF fixed

Equal RRF corrected both important Qwen rank-1 misses where lexical evidence was strong:

- long-term-memory database question: `memory_store` moved from semantic rank 2 to fused rank 1;
- webpage/memory-poisoning question: `memory_security` moved from semantic rank 2 to fused rank 1.

It also preserved semantic-only successes where FTS5 returned no useful candidates, including the Hinglish motorcycle query and Hindi research-rule query.

## Important regression

Equal-weight RRF is **not yet the final fusion configuration**.

For the Hinglish research-rule case, Qwen JARVIS 256 correctly ranked `research_rule` first, while noisy FTS5 ranked unrelated runtime/camera/provider memories above it. Equal-weight RRF therefore demoted the correct semantic result to fused rank 3.

This matters because the measured aggregate improvement must not hide a per-case regression.

## Tie evidence

Raw equal-weight RRF produced top-score ties in several cases (`eyes_en`, `self_model_en`, and `tyre_history`). The research harness broke exact ties using semantic rank, then lexical rank, then stable memory id. Production design must keep deterministic tie behaviour explicit rather than relying on container/set order.

## Current interpretation

1. Hybrid lexical + semantic retrieval is justified by measured JARVIS-specific evidence.
2. Qwen3-Embedding-0.6B with the JARVIS-specific instruction and 256-dimensional output remains the leading semantic model configuration.
3. Equal-weight RRF materially improves aggregate ranking with negligible additional latency.
4. Equal weighting is not yet approved because the lexical path is significantly weaker overall and caused one demonstrated regression.
5. Weighted RRF is a mature mechanism and should be measured next, favoring the empirically stronger semantic signal rather than inventing JARVIS-specific score arithmetic.
6. No vector database has been justified by these tests; exact cosine ranking remains sufficient for the research corpus and vector-index technology remains a scale-time decision.

## Next test

Run `tools/research/step4_weighted_rrf_bakeoff.py` on the same machine/runtime. It sweeps semantic weights 1.0, 1.25, 1.5, 1.75 and 2.0 against lexical weight 1.0, keeping RRF k=60 and the same corpus/query set.

The weight sweep is intended to answer one narrow question: can a standard modest semantic weighting preserve the lexical rescues while eliminating the equal-RRF regression?
