# Step 4 — Lexical Retrieval Probe

## Status

**RESEARCH EVIDENCE ONLY — NOT A RETRIEVAL TECHNOLOGY DECISION.**

This note records why Step 4 should benchmark semantic retrieval rather than assuming either that vectors are mandatory or that FTS5 alone is sufficient.

## Tiny paraphrase probe

A small reference-environment probe stored representative JARVIS memories in SQLite FTS5 and queried them using different wording. The query side used a simple OR-of-content-words lexical strategy. This is intentionally a lightweight baseline, not a tuned production query parser.

Result: **8 of 11 expected memories were ranked first**.

Successful examples included:

- `speaker echo barge in` -> self-echo incident;
- `memory should avoid sending private data away` -> privacy/local-memory rule;
- `Jimny wheel rubber size I chose` -> Jimny tyre preference;
- Hindi query with overlapping Hindi terms -> Hindi research-first rule;
- Hinglish query with overlapping English/Hinglish terms -> Hinglish research-first rule.

Important misses included:

- `which device gives Jarvis eyes` did not retrieve the camera memory first;
- `meri bike kaunsi hai` did not retrieve a memory phrased as `BMW G 310 GS motorcycle`;
- a Hinglish paraphrase meaning `find something already built; don't build it yourself` preferred a Hinglish memory with token overlap instead of the canonical English research-first rule.

## Interpretation

This is exactly the expected weakness of lexical retrieval: it is fast and useful when wording overlaps, but semantic/cross-lingual paraphrases may have little or no token overlap.

The result **does not justify immediately adding a vector database**. It justifies the next controlled comparison:

1. structured/exact lookup where a known fact key exists;
2. FTS5 BM25 baseline;
3. local multilingual embeddings on the same corpus;
4. only then decide whether a vector index is worth its complexity.

The embedding candidates retained from the broader research are:

- Qwen3-Embedding-0.6B;
- BGE-M3.

The semantic bake-off must include English, Hindi, Hinglish and cross-language queries, plus stale/superseded facts so semantic similarity cannot bypass temporal truth filtering.

## Required scoring

For each retrieval method record:

- top-1 accuracy;
- recall@3 / recall@5;
- stale/superseded memory leakage;
- irrelevant-memory injection;
- abstention on absent memories;
- p50/p95 retrieval latency;
- index size and rebuild time;
- CPU/RAM/VRAM load on the real JARVIS machine.

No acceptance threshold should be invented until the real baselines are measured.
