# Step 4 — Memory Extraction Provisional Tie

## Status

**HISTORICAL / PROVISIONAL EVIDENCE — NOT THE PHASE-4.4 PRODUCTION PROVIDER DECISION.**

**PROVISIONAL TIE ON SHARED EVIDENCE — NOT A FINAL 24-CASE WINNER.**

On 2026-09-04, JARVIS compared `gpt-5.6-terra` and `gemini-3.8-flash` using the then-current research memory-candidate extraction contract.

The OpenAI Terra run completed all 24 cases. Terra's important safety behaviour on that corpus was strong: zero false durable writes, zero missed durable candidates, 100% durable/non-durable flag accuracy, 100% untrusted-source handling, and 100% secret-policy handling. Terra had three core-label mismatches, primarily taxonomy/operation-label differences rather than unsafe writes.

Gemini 3.8 Flash completed only five cases before the free-tier quota prevented the remaining cases from being evaluated. Those five successful cases were 5/5 core-exact across English, Hindi, and Hinglish.

For a fair like-for-like comparison, only the five cases successfully evaluated by both providers were considered in this historical result:

- Terra: 5/5 core-exact;
- Gemini 3.8 Flash: 5/5 core-exact;
- false durable writes: 0 for both;
- missed durable candidates: 0 for both.

## Historical disposition

The providers were therefore recorded as a tie on the evidence available at that time. Do not claim either provider was the final extraction winner from this result.

The Phase-4.4 implementation subsequently removed research/production contract drift. The production-aligned harness now reuses the actual `MemoryExtractionProposal`, the actual production extraction system prompt, and the actual deterministic pre-provider gates. In particular, non-user sources, explicit Phase-4.3 commands, and locally detectable secrets are gated before provider extraction rather than asking the model to decide their authority.

Because that evaluation contract changed, the numerical results in this file are **not directly comparable** with future production-aligned Phase-4.4 bake-off results.

Current Phase-4.4 implementation decisions and acceptance requirements are recorded in:

`docs/research/STEP_4_PHASE_4_4_IMPLEMENTATION_DECISIONS.md`

The extraction architecture remains provider-swappable behind the JARVIS-owned `MemoryCandidateExtractor` contract. Provider output remains only a candidate proposal; JARVIS policy retains authority over admission, correction, supersession, retraction, forgetting, sensitivity, provenance, and truth.

## Original next research gate — completed later

At the time of this provisional tie, the next independent research gate was the Windows encryption/package spike. That work was later completed and is retained in the repository's SQLCipher/Windows acceptance records.

This historical tie never approved production durable-memory writes by a model and does not approve implicit auto-admission now.
