# Step 4 — Memory Extraction Provisional Tie

## Status

**PROVISIONAL TIE ON SHARED EVIDENCE — NOT A FINAL 24-CASE WINNER.**

On 2026-09-04, JARVIS compared `gpt-5.6-terra` and `gemini-3.8-flash` using the same fixed Step-4 memory-candidate extraction contract.

The OpenAI Terra run completed all 24 cases. Terra's important safety behaviour on that corpus was strong: zero false durable writes, zero missed durable candidates, 100% durable/non-durable flag accuracy, 100% untrusted-source handling, and 100% secret-policy handling. Terra had three core-label mismatches, primarily taxonomy/operation-label differences rather than unsafe writes.

Gemini 3.8 Flash completed only five cases before the free-tier quota prevented the remaining cases from being evaluated. Those five successful cases were 5/5 core-exact across English, Hindi, and Hinglish.

For a fair like-for-like comparison, only the five cases successfully evaluated by both providers are considered here. On that shared subset:

- Terra: 5/5 core-exact;
- Gemini 3.8 Flash: 5/5 core-exact;
- false durable writes: 0 for both;
- missed durable candidates: 0 for both.

## Disposition

**MARK THE TWO PROVIDERS AS A TIE ON THE CURRENT SHARED EVIDENCE.**

Do not claim either provider is the final extraction winner from this evidence. The unfinished 19 Gemini cases remain optional follow-up evidence and may break the tie later, but they do not block the independent Step-4 research gates.

The extraction architecture remains provider-swappable behind the JARVIS-owned `MemoryCandidateExtractor` contract. Provider output remains only a candidate proposal; JARVIS `MemoryPolicy` retains authority over admission, correction, supersession, retraction, forgetting, sensitivity, provenance, and truth.

## Next Step-4 research gate

Proceed to the independent **Windows encryption/package spike**. The current leading technology family is SQLCipher, but the Python/Windows packaging path and key-management integration must be proven on the real JARVIS machine before storing real personal memory.

The spike must verify at minimum:

1. a vetted Python 3.11 x64 Windows SQLCipher package/build path;
2. whole-database encryption actually active;
3. random database key generation;
4. Windows DPAPI protection of that database key;
5. successful reopen with the correct unwrapped key;
6. wrong-key failure;
7. plaintext leakage checks for canonical rows and FTS content;
8. FTS5/search behaviour while encrypted;
9. backup/restore and recovery behaviour;
10. forget/delete behaviour and derived-index cleanup;
11. dependency provenance and packaging reproducibility.

No production Step-4 memory implementation is approved by this tie disposition.