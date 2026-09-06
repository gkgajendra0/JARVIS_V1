# Step 4 Phase 4.5D — Composite Memory Gate Diagnostic Method

## Status

**FROZEN DEVELOPMENT-ONLY METHOD — NO NEW MODEL INFERENCE**

This diagnostic uses already exposed/retired development evidence only. It is architecture-selection evidence, not acceptance evidence, and cannot authorize Phase 4.5E.

## Research basis

The current provider-independent memory path follows complete-mediation / defense-in-depth principles:

1. the active BrainProvider may propose a structured query but has no release authority;
2. JARVIS validates proposal grounding and canonical facet policy;
3. deterministic lifecycle/security policy remains authoritative;
4. an independent local semantic guard may veto a release;
5. any disagreement fails closed.

This is consistent with current agent-security guidance to validate LLM-derived tool inputs downstream and to apply independent defense-in-depth controls.

## Inputs

The diagnostic requires both completed owner artifacts:

- `.step4-phase45d-v2-structured-query-planner-diagnostic-v1.json`
- `.step4-phase45d-v2-zero-shot-answer-type-diagnostic-v1.json`

It refuses to overwrite its own output:

- `.step4-phase45d-v2-composite-memory-gate-diagnostic-v1.json`

No Gemini, OpenAI, Qwen, mDeBERTa, embedding, reranker, or database inference is executed.

## Frozen composition rule

For every semantic-current case present in both artifacts:

```text
COMPOSITE_RELEASE =
    planner.final_disposition == "release"
    AND
    zero_shot.guard_allow == true
```

For security-boundary cases present only in the planner artifact, the planner's already-deterministic JARVIS result is preserved. They are not passed through the semantic classifier because the canonical eligibility boundary already owns those decisions.

The composite cannot convert an abstain into a release. It is strictly veto-only relative to the structured planner.

## Frozen evaluation set

Use the full 45-case structured-planner diagnostic set:

- 12 target releases;
- 33 target abstains;
- 30 semantic-current cases overlap the zero-shot artifact;
- 15 deterministic security-boundary cases remain planner/JARVIS-only.

The diagnostic must verify:

- planner artifact status and 45 unique case IDs;
- zero-shot artifact status and 30 unique case IDs;
- zero-shot IDs are exactly the non-security semantic-current subset expected by the frozen V2 selection;
- target labels/language/category agree for overlapping cases;
- no unknown case ID is accepted;
- output contains no user query text or canonical memory value.

## Frozen development continuation checks

The composite is promising for architecture review only if all are true:

1. zero false releases across all 33 target-abstain cases;
2. zero releases from historical/forgotten/local-only/secret/untrusted cases;
3. at least `10/12` target releases survive;
4. direct-current exact releases at least `8/9`;
5. relation-comparison exact releases at least `2/3`;
6. each EN/HI/Hinglish target-release recall at least `3/4`;
7. every composite release points to the exact expected memory ID;
8. composite is veto-only relative to the planner;
9. no new model/API calls are made.

These are development architecture-review gates only. Passing them does not change the accepted 4.5D production contract.

## Interpretation

### If all checks pass

The provider-independent architecture is promising enough to freeze for a **fresh acceptance design**:

```text
one central BrainProvider selector
→ structured query proposal only
→ local answer-type veto
→ deterministic JARVIS grounding/facet/lifecycle/security policy
→ exact canonical lookup
→ TrustedMemoryEvidence or ABSTAIN
```

A fresh, never-exposed acceptance corpus must then be designed before 4.5D can close.

### If any check fails

Do not tune either exposed artifact. Inspect the specific disagreement class and revise the typed query contract or deterministic policy before any fresh acceptance corpus is created.

## Explicit non-goals

- no threshold fitting;
- no prompt tuning;
- no provider comparison;
- no new semantic model;
- no reuse of exposed V2/V3 data as acceptance evidence;
- no 4.5E wiring.
