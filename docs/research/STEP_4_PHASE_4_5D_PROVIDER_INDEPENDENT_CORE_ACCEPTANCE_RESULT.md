# Step 4 Phase 4.5D — Provider-Independent Core Acceptance Result

## Status

**FAIL_CORE_ACCEPTANCE — V4 CORE EVIDENCE RETIRED**

Owner execution completed on 2026-09-07 from repository SHA:

`2c84ed011b223f502f5e8e6621554b83763168ce`

Artifact:

`.step4-phase45d-provider-independent-core-acceptance.json`

This harness made **zero cloud/provider calls** and therefore isolates the JARVIS-owned local semantic veto + deterministic memory authority from Gemini/OpenAI planner quality and quota.

## Result

- cases: 255;
- release targets: 90;
- abstain targets: 165;
- scripted interpreter calls: 66;
- cloud provider calls: **0**;
- released cases: 59;
- exact target releases: 58;
- false releases: **1**;
- wrong-target releases: **0**;
- security-boundary releases: **0**;
- security authority-precheck failures: **0**;
- empirical precision: 0.983051;
- overall recall: 58/90 = 0.644444;
- direct-current recall: 52/60 = 0.866667;
- current-value-comparison recall: 6/30 = 0.20.

By language:

- English: 20/30 = 0.666667;
- Hindi: 21/30 = 0.70;
- Hinglish: 17/30 = 0.566667.

Local answer-type guard veto counts on legitimate release families:

- `current_value_comparison`: **24**;
- `direct_current`: **8**.

The single false release was:

- `v4_a0073` — category `negation`, language `hinglish`.

## Diagnosis

This result transfers the dominant failure from the provider-backed acceptance into a zero-cloud/provider-independent harness. Therefore Gemini is **not** the primary 4.5D blocker.

The current local guard is a generic multilingual NLI checkpoint used as a seven-way zero-shot classifier. It is too conservative on legitimate current-value comparisons and insufficiently explicit about negation/contradiction.

At the same time, the deterministic authority/security layer performed correctly:

- zero security-boundary releases in the guarded path;
- zero security/lifecycle releases in the authority-only precheck that bypasses the local semantic guard;
- zero wrong-target releases.

So the next implementation target is narrow and JARVIS-owned: replace the generic zero-shot answer-type veto with a task-specific multilingual local classifier while preserving the deterministic authority/security/release layers unchanged.

## Decision

Do not tune or rerun V4 as acceptance.

Proceed with a fresh **development-only local classifier bake-off** using new training and holdout text that does not reuse V4 queries for training/model selection. After selecting and freezing a new guard architecture, create a new never-exposed V5 acceptance corpus.

Phase 4.5E remains blocked.
