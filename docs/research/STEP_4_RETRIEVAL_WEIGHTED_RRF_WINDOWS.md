# Step 4 — Weighted RRF Retrieval Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — STATIC RRF WEIGHT TUNING IS NOT SELECTED AS THE FINAL RANKING FIX.**

Date: 2026-09-04  
Machine: actual JARVIS Windows machine  
Embedding model: `Qwen/Qwen3-Embedding-0.6B`  
Embedding configuration: JARVIS-specific instruction, 256 dimensions, CUDA  
Lexical retrieval: SQLite FTS5  
Fusion: weighted Reciprocal Rank Fusion, rank constant 60

## Purpose

The preceding equal-weight RRF bake-off improved the fixed 17-positive-case corpus from Qwen-only Recall@1 0.8824 to hybrid Recall@1 0.9412, but introduced one regression: `rule_hi_mix` was correct for Qwen alone and became incorrect after noisy lexical results were fused.

This sweep tested whether a simple static semantic weight could remove that regression while preserving the two useful lexical rescues (`memory_db_mix` and `poison_en`).

Semantic weights tested with lexical weight fixed at 1.0:

- 1.0
- 1.25
- 1.5
- 1.75
- 2.0

## Measured result

| Semantic weight | Recall@1 | Recall@3 | MRR | Rank-1 misses |
|---:|---:|---:|---:|---|
| 1.00 | 0.9412 | 1.0000 | 0.9608 | `rule_hi_mix` |
| 1.25 | 0.9412 | 1.0000 | 0.9706 | `rule_hi_mix` |
| 1.50 | 0.9412 | 1.0000 | 0.9706 | `rule_hi_mix` |
| 1.75 | 0.9412 | 1.0000 | 0.9706 | `rule_hi_mix` |
| 2.00 | 0.8824 | 1.0000 | 0.9412 | `memory_db_mix`, `poison_en` |

The relevant transition is clear:

- through semantic weight 1.75, the noisy lexical ranking still prevents the correct research-rule memory from becoming rank 1;
- at semantic weight 2.0, the semantic signal finally fixes `rule_hi_mix`, but it becomes strong enough to undo both lexical rescues that motivated hybrid fusion in the first place.

Therefore there is **no acceptable static weight in the tested standard range** that simultaneously fixes all three disagreements.

## Performance context

The run reconfirmed the previously measured first-stage cost:

- FTS5 p50: ~0.63 ms
- FTS5 p95: ~1.19 ms
- Qwen query encode p50: ~60.85 ms
- Qwen query encode p95: ~63.97 ms
- peak CUDA allocation: ~1.29 GB

## Interpretation

Do not continue tuning a scalar weight until the tiny research corpus becomes perfect. That would be benchmark overfitting rather than architecture research.

The evidence now says:

1. SQLite FTS5 contributes real exact/lexical rescues.
2. Qwen semantic retrieval contributes real multilingual/paraphrase recall.
3. RRF is a useful first-stage candidate combiner.
4. A fixed global lexical/semantic weight cannot resolve every ranking disagreement in this corpus.
5. The remaining problem is **candidate ordering**, not candidate recall: the correct memory remains in the top 3 for every positive case.

That last point is important. The first-stage retrievers already have Recall@3 = 1.0 after semantic retrieval, so the mature next mechanism to evaluate is a **second-stage reranker over a small candidate set**, not another datastore or a more complex handcrafted fusion rule.

## Current disposition

- Keep SQLite structured/bitemporal truth as the leading canonical store.
- Keep FTS5 as the lexical retriever.
- Keep `Qwen3-Embedding-0.6B` with JARVIS-specific instruction and 256-dimensional output as the leading semantic retriever.
- Keep RRF as a candidate-fusion primitive.
- Do **not** lock a static semantic weight from this sweep.
- Benchmark a mature multilingual cross-encoder reranker next.

Current mature references:

- Sentence Transformers retrieve-and-rerank pattern: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Azure hybrid search / RRF / semantic reranking: https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
- Qwen3-Reranker-0.6B: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B

This remains research-only evidence and is not production implementation approval.
