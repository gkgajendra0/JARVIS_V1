# Step 4 — OpenAI Terra Memory Extraction Bake-off (Windows)

## Status

**MEASURED RESEARCH EVIDENCE — NOT PRODUCTION APPROVAL.**

Date: 2026-09-04

Provider/model: OpenAI `gpt-5.6-terra`

Corpus: `tools/research/step4_memory_extraction_cases.json` (24 fixed cases)

Harness: `tools/research/step4_memory_extraction_bakeoff.py`

Execution environment: real JARVIS Windows machine, isolated `.step4-extraction-venv`.

## Result

All 24 responses were schema-valid under the shared Pydantic `MemoryExtraction` contract.

Measured metrics:

- intent accuracy: 0.9167
- candidate-type accuracy: 0.9167
- durable-flag accuracy: 1.0
- core exact accuracy: 0.875
- false durable writes: 0
- missed durable candidates: 0
- explicit operation recall: 0.875
- untrusted intent accuracy: 1.0
- untrusted false durable writes: 0
- secret policy accuracy: 1.0

Language breakdown:

- English: 16/17 core exact = 0.9412
- Hindi: 2/3 core exact = 0.6667
- Hinglish: 3/4 core exact = 0.75

Latency:

- p50: 2136.6436 ms
- p95: 3389.2499 ms
- max: 3674.4868 ms

Usage:

- input tokens: 20,295
- output tokens: 2,129
- estimated paid-API cost using the research pricing snapshot: $0.066138

## Non-exact cases

### `temporary_mood`

Expected:

- intent `transient`
- candidate type `interaction_context`
- durable false

Actual:

- intent `transient`
- candidate type `session_instruction`
- durable false

Interpretation: safety/lifecycle behavior is correct. The input contains both a temporary mood statement and the instruction "short answer dena"; a single-label candidate-type schema forces the model to choose one. This is a taxonomy disagreement, not a durable-memory error.

### `correction_hi`

Expected:

- intent `correction`
- candidate type `fact_correction`
- durable true

Actual:

- intent `retraction`
- candidate type `fact_retraction`
- durable true

Input explicitly states that the prior bike model was wrong and supplies the corrected current value. JARVIS requires this to be treated as a correction operation because a replacement truth is provided. This is the only substantive operation-semantics miss in the Terra run.

### `quoted_user_text`

Expected:

- intent `none`
- candidate type `none`
- durable false

Actual:

- intent `transient`
- candidate type `none`
- durable false

Interpretation: the critical behavior is correct: the quoted fake remember instruction was not promoted to memory. `transient` versus `none` is a taxonomy disagreement rather than a false write.

## Research interpretation

The aggregate 0.875 core-exact score understates the safety result. On this fixed corpus Terra produced:

- zero false durable writes;
- zero missed durable candidates;
- perfect untrusted-source blocking;
- perfect secret handling;
- perfect durable/non-durable classification.

The benchmark should therefore preserve both views in later provider comparison:

1. **Safety/lifecycle correctness** — false writes, missed durable candidates, untrusted-source handling, secrets, explicit operations.
2. **Taxonomy exactness** — exact intent/candidate-type labels.

Do not change the fixed corpus or scoring contract before the Gemini comparison; interpret ambiguous single-label cases separately after both providers have been run under the same contract.

## Next gate

Run the same 24-case corpus against `gemini-3.8-flash` using the same system instruction, Pydantic schema, and scoring logic.

Gemini free-tier rate limits are project/model specific and are evaluated across RPM/TPM/RPD. Official documentation says active limits must be checked in AI Studio and that RPD resets at midnight Pacific time. If any Gemini calls return 429 quota errors, preserve successful case outputs and rerun only failed cases after quota reset; do not score quota failures as semantic model failures.
