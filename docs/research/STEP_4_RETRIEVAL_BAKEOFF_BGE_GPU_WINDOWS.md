# Step 4 — BGE-M3 Retrieval Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — NOT A FINAL EMBEDDING OR ARCHITECTURE APPROVAL.**

Date: 2026-09-04  
Machine: actual JARVIS Windows machine  
GPU: NVIDIA GeForce RTX 5060 Ti 8 GB  
Runtime: PyTorch 2.14.0 + CUDA 13.0  
Model: `BAAI/bge-m3`  
Harness: `tools/research/step4_memory_retrieval_bakeoff.py`  
Corpus: 14 research memories  
Queries: 20 total, 17 positive + 3 absent-answer cases

## Result summary

The run completed with `status = PASS` and `device = cuda:0`.

### Retrieval quality

| Method | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| SQLite FTS5 | 0.6471 | 0.7647 | 0.7275 |
| Qwen3-Embedding-0.6B GPU | 0.7647 | **1.0000** | 0.8824 |
| BGE-M3 GPU | **0.8824** | 0.9412 | **0.9265** |

BGE-M3 therefore produced the best raw rank-1 accuracy and MRR on this small JARVIS-specific corpus. It correctly fixed several cases Qwen ranked second, including the Hinglish bike query, Hinglish research-first rule, and memory-poisoning query.

However, BGE-M3 missed one positive case from the top three entirely: the Hinglish query asking which local database is leading for JARVIS long-term memory. It also ranked the self-knowledge memory second for the self-model query. Qwen placed every positive case somewhere in its top three.

### GPU performance and footprint

| Model | Query p50 | Query p95 | Corpus encode | Peak CUDA allocation |
|---|---:|---:|---:|---:|
| Qwen3-Embedding-0.6B | 61.0165 ms | 64.8851 ms | 0.6483 s | 1,292,429,824 B (~1.20 GiB) |
| BGE-M3 | **23.3788 ms** | **31.6977 ms** | **0.4372 s** | 2,333,283,840 B (~2.17 GiB) |

BGE-M3 is substantially faster on this GPU but consumes about **1.04 GB more CUDA allocation** than Qwen in the same harness. That resource difference is material because the JARVIS RTX 5060 Ti has 8 GB VRAM and vision/identity workloads also need GPU capacity.

The BGE `load_seconds = 684.8454` measurement is not a meaningful warm-start number because this was the first model download/cache population. It must not be compared with Qwen's cached warm load time.

### Absent-answer behaviour

For the three queries where no memory should answer, BGE-M3 still returned nearest neighbours with top scores from about **0.335 to 0.497**. Qwen's corresponding range was about **0.260 to 0.327**.

The BGE absent-score range overlaps scores of valid positive memories. Therefore no global similarity threshold should be guessed from this small corpus. Vector similarity remains candidate-retrieval evidence only; temporal, authority, sensitivity, scope and abstention policy remain separate controls.

## Current comparison disposition

1. **BGE-M3 is the current raw retrieval winner** on Recall@1, MRR and query latency.
2. **Qwen remains a serious efficiency candidate** because it uses roughly 1 GB less GPU memory and achieved Recall@3 = 1.0.
3. The final choice must consider JARVIS's total GPU budget, not embedding retrieval in isolation.
4. Do not add a vector database yet. Both embedding candidates are still being evaluated with exact cosine similarity so the model decision remains isolated from vector-store complexity.
5. One final Qwen-specific test is justified before selection: use a JARVIS-memory-specific query instruction instead of the model's generic web-search query instruction, and evaluate Matryoshka dimensions (1024/512/256). Qwen's official model card states that it supports user-defined task instructions and output dimensions 32–1024.
6. BGE-M3 does not require adding a query instruction according to its official model documentation, so the current BGE dense run is already representative of its standard Sentence Transformers retrieval path.

No production embedding model is approved by this document.
