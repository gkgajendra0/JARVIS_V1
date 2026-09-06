# Step 4 Phase 4.5D — V2 Retrieval-Depth Development Result

## Status

**DEVELOPMENT DIAGNOSTIC COMPLETE — TOP-3 CANDIDATE STARVATION CONFIRMED — TOP-10 SOLVES V2 POSITIVE RETRIEVAL/RERANKING — NOT ACCEPTANCE EVIDENCE**

This result uses the already-exposed V2 corpus only as development evidence. It does not reopen V2 acceptance and must not be cited as fresh final acceptance.

## Owner environment

- branch: `implementation/step-4-memory-context`
- exact owner-run SHA: `e99d8eae60f0ec49a0b04b445a3116c51efcc27c`
- accepted Windows `.venv`
- device: RTX 5060 Ti / CUDA
- production embedding contract remained `Qwen/Qwen3-Embedding-0.6B`, immutable revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, normalized 256d
- production reranker model remained `Qwen/Qwen3-Reranker-0.6B`, immutable revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`, frozen JARVIS memory instruction

Harness:

- `tools/research/step4_phase45d_v2_retrieval_depth_diagnostic.py`
- output: `.step4-phase45d-v2-retrieval-depth-diagnostic-v1.json`

## Measured result

The diagnostic reused all `900` V2 positive queries and measured first-stage candidate recall at increasing depths, then Qwen reranked Top-1 accuracy for increasingly wide candidate windows.

### First-stage candidate recall

| Candidate depth | Hits | Total | Recall |
|---:|---:|---:|---:|
| 3 | 799 | 900 | 0.887778 |
| 5 | 847 | 900 | 0.941111 |
| 10 | 900 | 900 | 1.000000 |
| 20 | 900 | 900 | 1.000000 |
| 50 | 900 | 900 | 1.000000 |
| 100 | 900 | 900 | 1.000000 |

### Qwen reranked Top-1 accuracy

| Rerank window | Correct Top-1 | Total | Accuracy |
|---:|---:|---:|---:|
| 3 | 799 | 900 | 0.887778 |
| 5 | 847 | 900 | 0.941111 |
| 10 | 900 | 900 | 1.000000 |
| 20 | 900 | 900 | 1.000000 |

## Interpretation

The identical first-stage recall and reranked Top-1 values at every measured depth are decisive on this exposed development corpus:

1. Qwen reranking is not the ranking bottleneck once the correct memory reaches the candidate set.
2. The V2 ranking failure came from truncating the hybrid first stage to only three candidates before reranking.
3. Increasing the candidate window to ten recovered every positive memory in the 900-case V2 development set.
4. The same frozen Qwen reranker then selected the correct memory for every one of those 900 cases.

This matches the standard retrieve-then-rerank architecture used by mature CrossEncoder systems: the retriever should provide a broader shortlist and the slower reranker should refine it rather than being starved by an overly narrow first-stage cutoff.

## Architecture decision from this diagnostic

For the next development experiments:

- retain Qwen3-Embedding-0.6B;
- retain normalized 256-dimensional embeddings;
- retain exact lexical + dense + equal-RRF first stage;
- retain Qwen3-Reranker-0.6B and the frozen JARVIS instruction;
- use a **10-candidate development rerank window**;
- do **not** spend another experiment on 512d/1024d embeddings unless later evidence shows a new retrieval failure;
- do **not** swap to BGE merely to fix the V2 retrieval miss, because the existing accepted Qwen stack already reaches 100% positive candidate recall and 100% reranked Top-1 on the exposed development set at depth ten.

This is not yet a production contract change. A future frozen architecture must still pass fresh acceptance before Phase 4.5D can close.

## Remaining blocker

The release-confidence architecture remains rejected.

V2 showed that the old `mMARCO -> StandardScaler + LogisticRegression -> MAPIE` gate could not produce a statistically valid 0.95-precision / 0.95-confidence threshold. The artifact also showed severe absolute-score shift between calibration and validation query wording. Therefore the next experiment must target **answerability / support**, not generic query-passage relevance.

## Next action

Run a development-only task-matched verifier bake-off using top-10 Qwen retrieval/reranking and a multilingual extractive-QA model trained with explicit unanswerable questions. If that verifier transfers robustly across the exposed V2 calibration/validation wording shift, freeze a new architecture and only then create a completely fresh V3 acceptance corpus.
