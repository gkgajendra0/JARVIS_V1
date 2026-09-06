from __future__ import annotations

import re
from pathlib import Path

DIGEST = "baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one match for: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    acceptance_path = Path("tools/research/step4_phase45d_final_v3_acceptance.py")
    acceptance = acceptance_path.read_text(encoding="utf-8")
    acceptance = replace_once(
        acceptance,
        'EXPECTED_V3_PAYLOAD_SHA256 = "__FREEZE_AFTER_CORPUS_CI__"',
        f'EXPECTED_V3_PAYLOAD_SHA256 = "{DIGEST}"',
    )
    acceptance_path.write_text(acceptance, encoding="utf-8")

    test_path = Path("tests/test_phase45d_final_v3_cases.py")
    test_text = test_path.read_text(encoding="utf-8")
    test_text = replace_once(
        test_text,
        "    assert first == second\n    assert len(first) == 64\n",
        (
            "    assert first == second\n"
            f'    assert first == "{DIGEST}"\n'
            "    assert len(first) == 64\n"
        ),
    )
    test_path.write_text(test_text, encoding="utf-8")

    method_path = Path("docs/research/STEP_4_PHASE_4_5D_FINAL_V3_METHOD.md")
    method = method_path.read_text(encoding="utf-8")
    method = replace_once(
        method,
        "Any payload-hash change creates a new V3 version and invalidates prior evidence.\n",
        (
            "Any payload-hash change creates a new V3 version and invalidates prior evidence.\n\n"
            "Frozen V3 payload SHA-256:\n\n"
            f"`{DIGEST}`\n"
        ),
    )
    method_path.write_text(method, encoding="utf-8")

    plan_path = Path("docs/CURRENT_PLAN.md")
    plan = plan_path.read_text(encoding="utf-8")
    plan = replace_once(
        plan,
        (
            "**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — "
            "PHASE 4.5D ACTIVE — TOP-10 QWEN DEVELOPMENT RETRIEVAL PASSED — "
            "QA + GLICLASS REJECTED — GEMINI SINGLE-INSTANCE BOUNDARY 15/15 PASSED — "
            "24-CASE PRODUCTION-SHAPE COVERAGE DIAGNOSTIC NEXT — PHASE 4.5E BLOCKED**"
        ),
        (
            "**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — "
            "PHASE 4.5D ACTIVE — QWEN TOP-10 + GEMINI SINGLE-INSTANCE DEVELOPMENT "
            "ARCHITECTURE SELECTED 39/39 — FRESH V3 METHOD/CORPUS/HARNESS FROZEN — "
            "OWNER V3 ACCEPTANCE NEXT — PHASE 4.5E BLOCKED**"
        ),
    )

    active_pattern = re.compile(
        r"## Active 4\.5D development direction — GEMINI SINGLE-INSTANCE COVERAGE DIAGNOSTIC\n"
        r".*?\n---\n\n## Phase 4\.5E — BLOCKED",
        re.S,
    )
    active_replacement = f"""## Active 4.5D direction — FRESH V3 ACCEPTANCE

Development architecture selection is complete. V2 remains exposed and retired and cannot be reused as acceptance evidence.

### Selected production-shaped architecture

The two preregistered single-instance diagnostics passed exactly:

- boundary cells: `15/15` correct;
- additional positive/ordinary-semantic cells: `24/24` preserved;
- combined production-shaped development coverage: `39/39`, zero regressions;
- EN, HI and Hinglish all represented.

Selected V3 pipeline:

```text
canonical eligibility/security authority
→ eligible FTS5 + Qwen3-Embedding-0.6B 256d exact cosine
→ equal-weight RRF, k=60
→ top 10
→ Qwen3-Reranker-0.6B with frozen instruction
→ eligible Top-1
→ gemini-3.5-flash-lite
→ exactly one query/document pair per Interactions API request
→ structured RELEASE / ABSTAIN
```

Durable development evidence:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI_SINGLE_INSTANCE_BOUNDARY_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_5D_GEMINI_SINGLE_INSTANCE_COVERAGE_RESULT.md`.

### Fresh V3 — METHOD/CORPUS/HARNESS FROZEN, NOT YET RUN

Frozen method:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V3_METHOD.md`.

Fresh corpus:

- `tools/research/step4_phase45d_final_v3_cases.py`;
- `720` cases total;
- calibration: `180 release + 180 abstain`;
- validation: `180 release + 180 abstain`;
- positive cases per split: `60 EN + 60 HI + 60 Hinglish`;
- every one of the 12 abstain families: `5 EN + 5 HI + 5 Hinglish` per split;
- calibration/validation synthetic profile identities are disjoint;
- exact V2 query reuse is prohibited;
- no real secrets;
- frozen payload SHA-256: `{DIGEST}`.

Acceptance harness:

- `tools/research/step4_phase45d_final_v3_acceptance.py`;
- Qwen candidate window `10`;
- Gemini Interactions API only;
- one query/document pair per request;
- fixed hard RELEASE/ABSTAIN policy, no fitted Gemini threshold and no fabricated confidence score;
- fresh calibration first;
- exact one-sided Clopper-Pearson precision lower bound via SciPy;
- precision target `0.95`, confidence `0.95`;
- at least `59` calibration releases required;
- validation API calls are blocked unless every calibration hard gate passes;
- validation requires zero false releases;
- output refuses overwrite;
- validation is never used for retuning.

The V3 owner run is now authorized once the frozen implementation reaches a clean exact SHA with all CI jobs green. This is still synthetic acceptance; later shadow-labelled operational monitoring remains required.

---

## Phase 4.5E — BLOCKED"""
    plan, count = active_pattern.subn(active_replacement, plan, count=1)
    if count != 1:
        raise RuntimeError("failed to replace active Phase 4.5D section")

    plan = replace_once(
        plan,
        (
            "9. **4.5D — ACTIVE: top-10 retrieval complete; boundary single-instance "
            "15/15 passed; 24-case coverage diagnostic next.**"
        ),
        (
            "9. **4.5D — ACTIVE: development architecture selected 39/39; fresh V3 "
            "method/corpus/harness frozen; owner V3 acceptance next.**"
        ),
    )
    plan = replace_once(
        plan,
        "- jump to BGE or multilingual NLI before resolving the frozen 24-case Gemini single-instance coverage diagnostic;",
        "- reopen rejected verifier/model search unless fresh V3 evidence fails the frozen selected architecture;",
    )
    plan = replace_once(
        plan,
        "- generate V3 before development architecture selection is complete;",
        "- alter the frozen V3 corpus, prompt, API shape, model revisions or gates after owner acceptance begins;",
    )

    immediate_pattern = re.compile(r"## Immediate Next Action\n.*\Z", re.S)
    immediate = f"""## Immediate Next Action

**PASS THE FROZEN FRESH V3 CORPUS/HARNESS THROUGH CI ON A CLEAN EXACT SHA, THEN RUN V3 ONCE ON THE OWNER RTX.**

The owner run must use payload SHA `{DIGEST}`, Qwen candidate window `10`, the Gemini Interactions API with exactly one query/document pair per request, and the exact statistical gates in `STEP_4_PHASE_4_5D_FINAL_V3_METHOD.md`.

If calibration fails, validation must remain unexecuted and this V3 is retired. If validation executes, it is exposed once and cannot be used to retune or rerun V3 as fresh evidence. Phase 4.5E remains blocked until a passing V3 result is durably recorded and closed on a green exact SHA.
"""
    plan, count = immediate_pattern.subn(immediate, plan, count=1)
    if count != 1:
        raise RuntimeError("failed to replace Immediate Next Action")
    plan_path.write_text(plan, encoding="utf-8")


if __name__ == "__main__":
    main()
