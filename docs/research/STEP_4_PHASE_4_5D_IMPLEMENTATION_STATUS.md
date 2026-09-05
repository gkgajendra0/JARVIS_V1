# Step 4 — Phase 4.5D Abstention Calibration Implementation Status

Date: 2026-09-06

## Status

**ACTIVE — V1 OWNER MEASUREMENT COMPLETE / PRODUCTION POLICY REJECTED / RERANKER-INSTRUCTION DEVELOPMENT NEXT.**

Phase 4.5D has produced one valid owner-RTX measurement. The 64-case V1 corpus is now retired from final acceptance use because its held-out labels have been exposed and reviewed.

The measured V1 policy had zero observed false releases but only `0.1875` held-out positive release recall and `0.0` Hindi positive release recall. It is therefore not acceptable for production memory release.

Owner evidence:

- `docs/research/STEP_4_PHASE_4_5D_OWNER_MEASUREMENT_V1.md`.

## V1 measurement interpretation

The V1 harness status string was `PASS`, but that status meant only:

- the calibration-only frozen policy produced zero observed false releases on the 32-case held-out validation split.

It did not mean production acceptance. The documented gate also required useful positive release recall and multilingual/category review.

Measured V1 selected policy:

- family: `score_margin`;
- score threshold: `8.96875`;
- margin threshold: `9.15625`.

Held-out result:

- `tp=3`;
- `fp=0`;
- reported precision `1.0`;
- positive release recall `0.1875`;
- English recall `0.166667`;
- Hindi recall `0.0`;
- Hinglish recall `0.333333`.

This is safe-looking in the observed sample but far too conservative to ship.

## Security-boundary correction discovered before V1

The first attempted V1 run failed before measurement because the fixture tried to instantiate `SECRET_PROHIBITED` canonical semantic memory. The canonical constructor correctly rejected that impossible state.

The harness was corrected without weakening production security:

- `mode=secret` remains a corpus marker;
- secret fixtures are excluded before canonical semantic-memory creation;
- release-labeled cases cannot target secret fixtures;
- output records which secret fixture IDs were excluded.

The successful owner run proved:

- corpus document markers: `23`;
- canonical seed documents: `22`;
- excluded secret fixture: `secret_placeholder`.

## Why threshold tweaking is not the next action

The Qwen reranker emits a true-vs-false raw logit-difference relevance score. A sigmoid can remap the numeric range but does not create a statistical field guarantee or improve score ordering.

The V1 result also exposed a finite-sample issue: only three held-out cases were released. Observing `3/3` correct releases is not enough evidence to claim production-level precision.

Therefore Phase 4.5D will not loosen V1 thresholds or tune against the exposed validation labels.

## Research-first update after V1

Two mature capabilities now define the next path.

### 1. Qwen reranker instruction awareness

`Qwen/Qwen3-Reranker-0.6B` is instruction-aware. Qwen recommends task-specific English instructions and reports typical downstream gains relative to its generic default web-search instruction.

The current JARVIS production adapter still instantiates the reranker without a custom prompt/instruction, so it uses the model's generic default.

Before adding another model, Phase 4.5D will compare:

- current default Qwen reranker instruction;
- exactly one pre-registered JARVIS-memory-specific English instruction.

This comparison uses the **retired V1 corpus only as a development set**. It cannot re-establish held-out acceptance.

Selection criteria will emphasize:

- positive top-1 ranking accuracy;
- positive hit@3;
- English/Hindi/Hinglish ranking quality;
- score separation between safe-to-release and unsafe top-1 results;
- risk-coverage / AURC behavior;
- zero changes to model ID, revision, precision, candidate window, embedding model, or first-stage retrieval.

After this experiment, the better instruction is frozen before constructing a new acceptance corpus.

### 2. Mature risk-control library instead of custom final threshold selection

For the fresh final corpus, Phase 4.5D will use MAPIE's binary risk-control / Learn-Then-Test machinery rather than promoting the V1 custom selector into production acceptance.

MAPIE is designed to calibrate decision thresholds against a pre-declared metric such as precision with a requested confidence level, and it can correctly return that no candidate threshold is statistically feasible.

MAPIE remains a **research/calibration dependency only**. Production runtime will receive only a frozen, versioned policy if final acceptance passes; production JARVIS does not need MAPIE at inference time.

## Retired V1 corpus

Files:

- `tools/research/step4_phase45d_abstention_cases.json`;
- `tools/research/step4_phase45d_abstention_calibration.py`.

The corpus contains 64 fixed queries:

- former calibration: 16 release + 16 abstain;
- former validation: 16 release + 16 abstain;
- English/Hindi/Hinglish;
- absent, near-miss, ambiguous, historical, forgotten, local-only, secret, untrusted, adversarial lexical, negation, and relation-mismatch boundaries.

From this point forward the entire V1 corpus is development-only because all labels/results have been exposed.

## Existing production-path harness properties

The V1 harness uses the actual production retrieval path against a temporary migrated SQLite database:

- `MemoryLifecycleService`;
- `SemanticEmbeddingStore`;
- `SemanticRetrievalService`;
- `RetrievalEligibility.cloud_context()`;
- revision-pinned `Qwen3EmbeddingEncoder`;
- revision-pinned top-3 `Qwen3RetrievalReranker`.

It never reads the owner's production memory database and never auto-writes a production policy.

## Authority/security boundaries

Phase 4.5D continues to enforce:

- no production canonical-memory mutation from research harnesses;
- no `SECRET_PROHIBITED` canonical memory;
- no cloud provider for local retrieval scoring/calibration;
- no second cloud subscription;
- no retrieval eligibility bypass;
- no implicit durable admission;
- no self-repair/code-modification authority;
- no tuning against a final held-out corpus after labels are exposed.

## Next gate

1. Add opt-in task instruction support to the Qwen reranker adapter without changing the current default behavior.
2. Run a research-only default-vs-JARVIS-instruction bake-off on the retired V1 corpus.
3. Freeze the winning instruction.
4. Pre-register the final risk/coverage target and MAPIE Learn-Then-Test method.
5. Build a fresh multilingual acceptance corpus.
6. Perform one final calibration/validation run.

Phase 4.5E remains blocked until the fresh Phase 4.5D acceptance passes.
