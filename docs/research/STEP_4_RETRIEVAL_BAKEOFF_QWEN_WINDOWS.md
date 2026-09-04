# Step 4 — Qwen Retrieval Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — NOT A FINAL EMBEDDING OR ARCHITECTURE APPROVAL.**

This note records the first real-machine semantic retrieval run for Step 4. It complements `STEP_4_BAKEOFF_RESULTS.md` and keeps the raw decision-relevant evidence separate from the final architecture decision.

Date: 2026-09-04
Machine: actual JARVIS Windows machine
Model: `Qwen/Qwen3-Embedding-0.6B`
Harness: `tools/research/step4_memory_retrieval_bakeoff.py`
Corpus: 14 research memories
Queries: 20 total, 17 positive + 3 absent-answer cases

## Result summary

The run completed with `status = PASS`.

### Retrieval quality

| Method | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| SQLite FTS5 | 0.6471 | 0.7647 | 0.7275 |
| Qwen3-Embedding-0.6B | 0.7647 | 1.0000 | 0.8824 |

Measured gain from Qwen over FTS5 on this small corpus:

- Recall@1: +0.1176 absolute (~18.2% relative improvement over the FTS baseline)
- Recall@3: +0.2353 absolute; all 17 positive cases were present in the top 3
- MRR: +0.1549 absolute

This is sufficient evidence that semantic retrieval can recover useful paraphrases that lexical retrieval misses. It is **not** sufficient evidence to replace structured lookup or FTS5. The current research direction remains hybrid: exact/temporal filtering first, FTS5 as a cheap lexical path, semantic retrieval only where it adds measured value.

### Examples semantic retrieval fixed

Qwen correctly ranked the expected memory first for cases that FTS5 missed, including:

- `which device gives Jarvis eyes?` -> camera
- Hindi research-first query -> research rule
- self-model / how-JARVIS-is-built query -> self-knowledge
- historical tyre query -> old tyre memory

### Remaining Qwen misses at rank 1

Qwen still missed several important cases:

- Hinglish bike query: ranked `jimny` above the motorcycle memory; the correct bike memory was rank 2
- Hinglish research-rule query: ranked the echo incident slightly above the research rule; the correct memory was rank 2
- Hinglish memory-database query: ranked provider-boundary above memory-store; correct memory was rank 2
- memory-poisoning query: ranked provider-boundary above memory-security; correct memory was rank 2

Because Recall@3 was 1.0, the current evidence supports **candidate retrieval followed by deterministic filtering/reranking**, not treating nearest-vector rank 1 as truth.

### Absent-answer evidence

For the 3 queries where no memory should answer, Qwen still returned nearest neighbours with top similarity scores between about 0.262 and 0.329.

Therefore:

- vector search must never imply that a memory exists merely because the nearest neighbour has a score;
- an abstention/acceptance threshold must be calibrated on a larger corpus rather than guessed;
- structured scope, authority, sensitivity and temporal filters must run independently of semantic similarity.

## Performance result — CPU-only run

The model reported:

- device: `cpu`
- parameters: 595,776,512
- embedding dimension: 1024
- model load: 255.3758 s (includes first-run/download/cache effects and therefore is not a warm-start runtime number)
- corpus encoding: 25.6816 s for the tiny research corpus
- query encode p50: 954.547 ms
- query encode p95: 1941.692 ms

This CPU latency is unacceptable for the normal realtime conversational retrieval path.

However, the result does **not** reject Qwen yet because the actual JARVIS machine has an NVIDIA GPU and this research environment installed generic PyPI `torch==2.14.0`, which resulted in a CPU execution path. The model must be rerun with an official CUDA-enabled PyTorch build before a latency/resource decision is made.

Current official PyTorch Windows instructions provide CUDA wheels through the PyTorch wheel index (for example PyTorch 2.13.0 with CUDA 13.0/13.2). The research environment must use an official CUDA wheel rather than assuming a generic PyPI torch install will use the GPU.

## Current disposition

1. **Semantic retrieval is justified for further testing**: Qwen materially improved retrieval quality over FTS5 on the first multilingual/paraphrase corpus.
2. **Qwen is not approved yet**: rank-1 mistakes remain, absent-answer calibration is unresolved, and CPU latency is far too high.
3. **Do not add a vector database yet**: the current test proves embedding usefulness with plain cosine similarity; it does not prove Qdrant/LanceDB or any second physical store is needed.
4. **Next test is GPU validation**, then BGE-M3 under the same hardware/runtime conditions.
5. Final selection must compare quality + p50/p95 latency + GPU memory + model footprint + multilingual behaviour.

## Next owner-machine command

Before changing packages, verify the research environment's current torch/CUDA status:

```powershell
.\.step4-retrieval-venv\Scripts\python.exe -c "import torch; print('torch=', torch.__version__); print('torch_cuda=', torch.version.cuda); print('cuda_available=', torch.cuda.is_available()); print('device=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')"
```

Record that output before installing a CUDA build so the CPU-only cause is explicit in the evidence trail.
