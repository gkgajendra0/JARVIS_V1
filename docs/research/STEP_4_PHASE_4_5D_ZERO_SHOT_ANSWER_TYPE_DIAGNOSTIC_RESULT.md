# Step 4 Phase 4.5D — Zero-Shot Answer-Type Diagnostic Result

## Status

**DEVELOPMENT-ONLY — STANDALONE ZERO-SHOT GUARD REJECTED; COMPLEMENTARY VETO SIGNAL RETAINED FOR COMPOSITE REVIEW**

This result is not acceptance evidence and does not authorize Phase 4.5E.

## Owner result

The owner ran the frozen 30-case local multilingual zero-shot diagnostic on the accepted RTX 5060 Ti / Torch environment.

Model:

- `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- revision `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- mode: multilingual zero-shot answer-type classification
- no Gemini calls
- no Qwen calls
- no threshold fitting

Observed result:

- 30 semantic-current development cases;
- 12 allow targets;
- 18 veto targets;
- allowed target cases: `12/12`;
- false vetoes: `0`;
- false allows: `2/18`;
- allow-target recall: `1.0`;
- veto specificity: `0.888889`;
- EN allow recall: `4/4`;
- HI allow recall: `4/4`;
- Hinglish allow recall: `4/4`;
- direct-current allows: `9/9`;
- relation-comparison allows: `3/3`.

False allows:

- `v2_val_a0002` — Hindi `absent`;
- `v2_val_a0003` — Hinglish `absent`.

The frozen V2 `absent` template asks for a different missing relation (`parking permit zone`) while mentioning the known stored value/relation only as context. The classifier therefore still occasionally confuses contextual known-memory language with the requested answer slot.

## Interpretation

The standalone zero-shot guard does **not** satisfy the frozen zero-false-allow continuation gate and is therefore rejected as a sole release authority.

However, the error pattern is complementary to the already completed structured-query-planner diagnostic:

- the Gemini structured planner abstained on all three `absent` cells;
- its six false releases were in `near_miss`, `adversarial_lexical`, `negation`, and `unsupported_source`;
- the zero-shot classifier's only false allows were two `absent` cells;
- it allowed all 12 legitimate current-value/comparison targets.

This means the local classifier remains useful as an **independent veto signal**, but never as canonical truth or standalone release authority.

## Architecture implication

The next development architecture to review is strict fail-closed consensus:

```text
active BrainProvider structured query proposal
        AND
local answer-type guard says current_value/current_value_comparison
        AND
JARVIS grounding + canonical facet policy
        AND
deterministic lifecycle/security eligibility
        -> exact canonical lookup

otherwise -> ABSTAIN
```

The planner and local guard are advisory/selective components. JARVIS application policy remains the release authority.

No component may resurrect forgotten, historical-only, local-only, secret-prohibited, or untrusted data.

## Decision

- Standalone zero-shot guard: **REJECTED**.
- Threshold tuning: **NOT AUTHORIZED**.
- Model hopping: **NOT AUTHORIZED from this result**.
- Complementary veto role: **PROMISING FOR COMPOSITE DEVELOPMENT REVIEW**.
- Fresh acceptance: **NOT YET AUTHORIZED**.
- Phase 4.5E: **BLOCKED**.
