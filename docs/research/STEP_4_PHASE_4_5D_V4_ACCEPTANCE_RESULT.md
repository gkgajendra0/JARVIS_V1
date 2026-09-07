# Step 4 Phase 4.5D — V4 Acceptance Result

## Status

**RETIRED ACCEPTANCE EVIDENCE — FAILED; DO NOT TUNE OR RERUN V4**

The fresh V4 corpus is now exposed and is retired for acceptance. It must not be used to fit thresholds, train a replacement classifier, select a replacement model, or claim a later pass.

Frozen V4 corpus SHA-256:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

Phase 4.5E remains blocked.

## Provider-backed final composite acceptance

The quota-safe owner run completed all 255 cases with exactly 66 logical Gemini calls and 66 API attempts. Quota was therefore not the blocker in this run.

Result: `FAIL_ACCEPTANCE`

| Metric | Result |
| --- | ---: |
| cases | 255 |
| release targets | 90 |
| abstain targets | 165 |
| exact target releases | 53 |
| false releases | 0 |
| wrong-target releases | 0 |
| security-boundary releases | 0 |
| empirical precision | 1.000000 |
| one-sided 95% precision lower bound | 0.945045 |
| overall release recall | 0.588889 |
| direct-current recall | 0.800000 |
| comparison recall | 0.166667 |
| English release recall | 0.666667 |
| Hindi release recall | 0.566667 |
| Hinglish release recall | 0.533333 |
| provider logical calls / attempts | 66 / 66 |

The local answer-type guard vetoed 24 of 30 legitimate `current_value_comparison` targets and 8 direct-current targets. This was the dominant recall failure.

## Provider-independent core acceptance

The already-frozen provider-independent core harness was then run with zero cloud/provider calls and a deterministic hostile proposal map.

Result: `FAIL_CORE_ACCEPTANCE`

| Metric | Result |
| --- | ---: |
| cases | 255 |
| exact target releases | 58 |
| false releases | 1 |
| false release | `v4_a0073` |
| false-release category | `negation` |
| false-release language | Hinglish |
| wrong-target releases | 0 |
| security-boundary releases | 0 |
| security authority-precheck failures | 0 |
| empirical precision | 0.983051 |
| overall release recall | 0.644444 |
| direct-current recall | 0.866667 |
| comparison recall | 0.200000 |
| English release recall | 0.666667 |
| Hindi release recall | 0.700000 |
| Hinglish release recall | 0.566667 |
| cloud/provider calls | 0 |

The same local guard again vetoed 24 of 30 legitimate comparison targets. It also allowed one Hinglish negation query through, which the deliberately hostile exact-fact proposal converted into a false release.

## Diagnosis

The two independent runs isolate the failure class:

1. Gemini transport/quota is not the blocker.
2. Provider planning quality is not the dominant blocker because the zero-cloud deterministic-proposal run fails in nearly the same place.
3. Canonical lifecycle/security authority is behaving correctly: the authority-only precheck produced zero security/lifecycle releases.
4. Exact canonical current-facet lookup is behaving correctly on allowed legitimate requests.
5. The generic multilingual NLI zero-shot answer-type guard is the blocker:
   - it is materially over-conservative on legitimate value comparisons;
   - it does not model negation strongly enough for this release-boundary task.

## Decision

Retire the current generic NLI zero-shot answer-type guard as the selected production design for Phase 4.5D.

Do **not**:

- rerun V4;
- tune a probability threshold on V4;
- train a replacement on V4 query text;
- score replacement candidates on V4;
- weaken canonical lifecycle/security filters;
- change Qwen retrieval/reranking because this failure is not a retrieval failure;
- move to Phase 4.5E.

Next action: run a development-only, zero-cloud, task-specific local guard bake-off on a completely new train/holdout corpus. V4 may be used only as an exact-query deny-list and as architectural evidence that comparison and negation must be represented explicitly.
