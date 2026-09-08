# Step 4 Phase 4.5D — Composite Memory Gate Diagnostic Result

Date: 2026-09-06

Status: `DEVELOPMENT_COMPOSITE_MEMORY_GATE_DIAGNOSTIC_COMPLETE`

This document records development-only evidence from the frozen composite diagnostic. The source V2 queries are exposed and retired; this result is **not acceptance evidence** and does not authorize Phase 4.5E.

## Frozen composition

The tested composition was fail-closed and veto-only:

```text
provider-selected structured planner release
AND
local multilingual answer-type guard allow
AND
JARVIS deterministic grounding / lifecycle / eligibility / exact-facet authority
→ release exact canonical current fact

otherwise
→ abstain
```

The local guard cannot create a release, select a different memory, restore forgotten/historical data, or override eligibility/security. `JARVIS_AI_PROVIDER` remains the single production brain/provider selector; the local guard is JARVIS-owned policy machinery rather than another brain provider.

## Result

The owner-run artifact was `.step4-phase45d-v2-composite-memory-gate-diagnostic-v1.json`.

Summary:

- cases: 45
- target releases: 12
- target abstains: 33
- planner releases before local veto: 16
- composite releases: 10
- exact target releases: 10
- false releases: **0**
- target-release recall: **10/12 = 83.33%**
- direct exact releases: **8/9**
- relation-comparison exact releases: **2/3**
- English: **4/4**
- Hindi: **3/4**
- Hinglish: **3/4**
- wrong-target releases: **0**
- security-boundary releases: **0**

The local guard vetoed exactly the six planner false releases observed in the prior structured-planner diagnostic:

- adversarial lexical: 1
- near miss: 2
- negation/replacement: 2
- unsupported source/provenance: 1

The zero-shot guard's two standalone `absent` false allows did not become composite releases because the structured planner had already abstained on those cases. The two components therefore showed complementary failure modes on this exposed diagnostic.

## Frozen continuation checks

All predeclared composite checks passed:

- zero false releases: PASS
- zero security-boundary releases: PASS
- at least 10/12 exact target releases: PASS
- at least 8/9 direct exact releases: PASS
- at least 2/3 relation-comparison exact releases: PASS
- each language at least 3/4: PASS
- every composite release is the exact expected canonical memory: PASS
- composite is veto-only: PASS
- zero new model/API calls during composition: PASS

`promising_for_fresh_acceptance_design = true`

`phase45e_authorized = false`

## Decision

The provider-independent composite memory gate is selected as the **development architecture candidate** for a fresh acceptance design.

This ends model hunting for Phase 4.5D. The next work is implementation and acceptance of the selected architecture, not another provider/model bake-off.

The production-shaped contract to implement is:

```text
active BrainProvider
→ structured MemoryQueryProposal (proposal only)
→ JARVIS grounding / canonical facet validation
→ local multilingual answer-type veto
→ deterministic lifecycle / sensitivity / authority eligibility
→ unique exact current-facet lookup
→ TrustedMemoryEvidence or ABSTAIN
```

For exact validated current-fact queries, Qwen embedding/reranking is not part of the release path. Broad/semantic recall remains a separate future path and does not gain automatic release authority from this result.

## Acceptance boundary

Before Phase 4.5D can close:

1. move the local answer-type guard out of the research harness into a reusable JARVIS memory component;
2. compose it with the provider-neutral planner and deterministic evidence gate in production-shaped code;
3. commit a completely fresh, previously unseen multilingual acceptance corpus and immutable corpus hash before the owner run;
4. run the selected architecture once on that fresh corpus under fail-closed gates;
5. do not tune against exposed validation evidence or reuse retired V2/V3 material as acceptance.

Phase 4.5E remains blocked until the fresh acceptance passes.