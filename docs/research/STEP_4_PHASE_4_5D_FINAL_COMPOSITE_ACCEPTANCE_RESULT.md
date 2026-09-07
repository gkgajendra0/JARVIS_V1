# Step 4 Phase 4.5D — Fresh V4 Composite Acceptance Result

## Status

**FAIL_ACCEPTANCE — V4 RETIRED / DO NOT TUNE AND RERUN**

Owner execution completed on 2026-09-07 from repository SHA:

`2c84ed011b223f502f5e8e6621554b83763168ce`

Unlike the previous quota-interrupted attempt, this execution completed all 255 frozen cases and wrote the final artifact:

`.step4-phase45d-final-composite-acceptance.json`

The quota-safe execution contract worked as intended:

- local quota plan: 255 remaining cases, 66 provider calls required;
- active RPD supplied to the harness: 500 limit / 0 used;
- safety reserve: 50 requests;
- Gemini pacing: 10 RPM below the 15 RPM project limit;
- provider logical calls: 66;
- provider API attempts: 66;
- SDK retries: 0;
- harness retries: 0;
- no quota or transport interruption.

## Frozen acceptance result

- target release cases: 90;
- target abstain cases: 165;
- released cases: 53;
- exact target releases: 53;
- false releases: **0**;
- wrong-target releases: **0**;
- security-boundary releases: **0**;
- empirical released precision: **1.0**;
- one-sided 95% exact released-precision lower bound: **0.945045**;
- overall release recall: **53/90 = 0.588889**;
- direct-current exact releases: **48/60 = 0.80**;
- current-value-comparison exact releases: **5/30 = 0.166667**.

By language:

- English: 20/30 = 0.666667;
- Hindi: 17/30 = 0.566667;
- Hinglish: 16/30 = 0.533333.

Local answer-type guard veto counts on legitimate release families:

- `current_value_comparison`: **24**;
- `direct_current`: **8**.

## Interpretation

The architecture remained extremely conservative and produced no false, wrong-memory, or security-boundary releases, but it failed the frozen recall gates. The dominant failure is the local multilingual zero-shot answer-type guard rejecting legitimate current-value-comparison questions before the provider planner can act.

The precision lower-confidence-bound gate also failed, but this is a consequence of only 53 successful releases: empirical precision remained 1.0 with zero false releases.

This result is model-quality / architecture evidence, not quota evidence. The Gemini quota-safe execution layer completed successfully.

## Decision

V4 is now exposed and retired acceptance evidence.

Do not:

- tune thresholds, prompts, labels, or the local guard on V4 and rerun it as fresh acceptance;
- rerun the same V4 acceptance to seek a pass;
- lower precision or recall gates;
- attribute this failure to Gemini quota.

The next diagnostic boundary is the provider-independent JARVIS-owned core, followed by redesign of the local semantic guard if the same failure transfers.

Phase 4.5E remains blocked.
