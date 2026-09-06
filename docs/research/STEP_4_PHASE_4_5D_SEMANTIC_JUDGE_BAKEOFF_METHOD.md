# Step 4 Phase 4.5D — Semantic Judge Development Bake-off Method

Date: 2026-09-06

Status: **DEVELOPMENT METHOD — NOT ACCEPTANCE**

## Why this experiment exists

Phase 4.5D V2 established two separate facts:

1. the old top-3 retrieval window starved the Qwen reranker;
2. the mMARCO + learned confidence architecture did not transfer.

The subsequent retrieval-depth diagnostic solved the first problem: the existing 256d Qwen stack achieved `900/900` positive first-stage recall and `900/900` reranked Top-1 at candidate depth 10.

The subsequent multilingual SQuAD2 answerability verifier still failed semantic sufficiency on exposed V2 validation:

- precision `0.921053` at the calibration-selected threshold;
- 9 relation-mismatch false releases;
- 1 ambiguous false release;
- 2 historical false releases;
- 2 security-boundary releases.

The next question is therefore no longer retrieval or extractive answerability. It is whether a mature semantic classifier/judge can distinguish **direct and sufficient answer evidence** from merely related, temporally wrong, ambiguous or unsupported evidence.

## Scope and evidence rules

This experiment uses the already-exposed V2 corpus only.

Therefore:

- it is development evidence only;
- V2 validation may be used to compare architectures because V2 is already retired;
- no V2 result may be called fresh acceptance;
- any selected architecture must later undergo a completely fresh V3 calibration/validation protocol;
- Phase 4.5E remains blocked.

## Frozen retrieval path

Do not alter retrieval while running this bake-off.

- `Qwen/Qwen3-Embedding-0.6B`
- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- normalized 256d
- eligible-current FTS5 + exact cosine + equal-weight RRF
- first-stage candidate window `10`
- `Qwen/Qwen3-Reranker-0.6B`
- revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`
- frozen JARVIS memory reranker instruction

The bake-off may reuse the development retrieval helper from the answerability experiment. It must not change production retrieval defaults yet.

## Challenger A — local GLiClass Multilang Mini

Model:

`knowledgator/gliclass-multilang-mini`

Pinned development revision:

`c09fb5ca4cb7957044168e6bf8bcefa2e14b8dfb`

Package:

`gliclass==0.1.20`

Why it is justified:

- Apache-2.0;
- about 288M parameters / about 568 MB safetensors;
- natively trained on 20 languages including Hindi;
- cross-lingual labels/text supported;
- explicitly documents hallucination detection, NLI and rule-following verification as supported uses;
- current package requires Torch >=2, Transformers >=5 and NumPy >=2, compatible with the accepted JARVIS retrieval environment;
- published zero-shot multilingual average is stronger than the model-card BGE-M3 zero-shot and mDeBERTa baselines.

Input to the model must contain only:

- the query;
- the selected memory document;
- the fixed task instruction.

The model must not receive case ID, split, language label, expected memory ID, ground-truth label or negative category.

Use two fixed semantic labels:

- release: the memory directly and sufficiently answers the exact query, including the requested relation and temporal scope;
- abstain: the memory does not directly and sufficiently answer the exact query.

Record both label scores and use `release_score - abstain_score` as the scalar development signal.

Select any scalar threshold from V2 calibration only. Evaluate the selected threshold unchanged on V2 validation.

## Challenger B — Gemini 3.5 Flash-Lite structured semantic judge

Model:

`gemini-3.5-flash-lite`

Why it is justified:

- GA/stable Gemini model;
- current production JARVIS cloud-provider family;
- structured JSON output is supported;
- designed for low-cost high-throughput subagent/classification work;
- no second production cloud provider/account is introduced;
- the repository already uses the Gemini async Interactions structured-output pattern for memory extraction.

The semantic-judge instruction must require `RELEASE` only when the document directly and sufficiently answers the exact query using facts explicitly stated in the document.

The following must force `ABSTAIN`:

- relation mismatch;
- temporal/current-vs-historical mismatch;
- ambiguity;
- negation/contradiction;
- missing requested detail;
- unsupported inference;
- merely topical/relevant evidence.

The input may contain query + selected memory document only. Ground-truth metadata is prohibited.

Use a minimal structured response:

- `decision`: `release` or `abstain`;
- `failure_mode`: `none`, `relation_mismatch`, `temporal_mismatch`, `ambiguous`, `negated_or_contradictory`, `missing_or_unsupported`, or `other`.

`failure_mode` is diagnostic only and must never be treated as ground truth.

To reduce API-call count without leaking labels, the harness may group a small fixed number of independent query/document cases in one request. The system prompt must explicitly require independent classification and exact index preservation.

Record API latency and any available token-usage metadata.

## Conservative conjunction

Because the same model calls already exist, also measure this no-extra-cost policy:

`Gemini decision == release AND GLiClass margin >= calibration-selected threshold`

The GLiClass threshold must still come from calibration only.

This conjunction is development evidence only. It exists to determine whether orthogonal local + cloud evidence materially improves safety without collapsing recall.

## Development metrics

For each challenger and the conjunction report:

- calibration TP / FP / precision / positive release recall;
- validation TP / FP / precision / positive release recall;
- EN / HI / Hinglish validation positive release recall;
- validation false-release IDs;
- false releases by category;
- security-boundary release IDs;
- runtime;
- model/package/environment metadata.

GLiClass additionally reports score ROC-AUC / AP and safe-vs-unsafe score quantiles.

Gemini additionally reports decision counts, failure-mode counts and token/call statistics when available.

## Development selection gates

A candidate may be called `promising_for_v3_design` only if all of these hold on exposed V2 development evaluation:

- calibration threshold/decision exists;
- validation precision >= `0.95`;
- validation positive release recall >= `0.40`;
- EN positive release recall >= `0.25`;
- HI positive release recall >= `0.25`;
- Hinglish positive release recall >= `0.25`;
- zero validation releases from `historical`, `forgotten`, `local_only`, `secret`, `untrusted`.

These are development gates, not 95%-confidence acceptance guarantees.

## What this experiment must not do

Do not:

- alter Qwen embedding dimensions;
- swap Qwen embedding or ranking models;
- tune GLiClass threshold on V2 validation;
- give labels/categories to either verifier;
- use self-reported Gemini confidence as calibrated probability;
- weaken canonical eligibility/security filters;
- modify ContextAssembler/Gemini conversation integration;
- generate V3 data before the semantic-judge architecture question is resolved;
- begin Phase 4.5E.
