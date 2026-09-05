# Step 4 — Phase 4.3 Owner-PC Acceptance

## Status

**OWNER-PC PACKAGE + ENCRYPTED ADAPTER: PASS.**

**DURABLE CROSS-PROCESS PERSISTENCE: PASS.**

**CROSS-SESSION VOICE RECALL: PASS.**

**EXPLICIT VOICE CORRECTION: PASS.**

**CROSS-SESSION CORRECTED-VALUE RECALL: PASS.**

**CROSS-SESSION VOICE ACCEPTANCE: IN PROGRESS.**

Date: 2026-09-05

This record captures the real JARVIS Windows owner-machine acceptance evidence for the first production persistent-memory rollout. It does not mark Phase 4.3 complete until the cross-session voice remember/inspect/correct/forget sequence and the remaining safety checks pass.

## 1. Retained SQLCipher package integrity — PASS

The retained JARVIS SQLCipher 4.17.0 CPython 3.11 Win64 wheel was downloaded from the successful GitHub Actions artifact and installed into the owner machine's existing `.venv` only after SHA-256 verification.

Wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Expected SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Owner-machine measured SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Result: **MATCH / PASS**.

Pip then reported successful installation of:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170`

## 2. Production encrypted-memory adapter smoke — PASS

The owner machine ran:

`tools/research/step4_sqlcipher_production_adapter_smoke.py`

using the installed retained wheel and the production `SqlCipherMemoryDatabaseFactory` + Windows DPAPI boundary.

Measured runtime:

- SQLCipher: `4.17.0 community`;
- SQLite: `3.53.3`;
- result: `PASS`;
- leaks: `[]`.

Every production-adapter assertion passed:

- `cipher_status`;
- `cipher_version`;
- `sqlite_version`;
- migration version;
- single migration ledger entry;
- FTS first-open synchronization;
- encrypted reopen current assertion;
- encrypted reopen FTS;
- DPAPI-protected key sidecar exists;
- stdlib plaintext SQLite open blocked;
- synthetic memory marker absent from storage artifacts.

The smoke used a disposable owner-PC temporary directory under `%TEMP%`; it did not write the real personal-memory database.

## 3. Initial one-line version probe note

A convenience PowerShell/Python one-line probe failed to parse because nested quoting was malformed. This was a command-quoting issue only and is not a product failure. The subsequent production-adapter smoke directly proved the required SQLCipher and SQLite engine versions and all production adapter checks.

## 4. First real voice remember — PASS

With `JARVIS_MEMORY_ENABLED=true`, the normal production voice runtime started without changing provider-native turn detection or the accepted Step-3 audio/vision architecture.

The owner explicitly said:

`Remember that my phase 4 test city is Sagar.`

JARVIS acknowledged the explicit remember request. The process was then returned to idle and fully stopped.

## 5. First cross-session voice recall — FAIL, ROOT CAUSE FIXED

On a new production process/session, the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The realtime tool attempted predicate `phase_four_test_city` and returned no current memory.

This exposed a deterministic key-normalization defect rather than a storage/encryption failure: the original remembered target canonicalized to `phase_4_test_city`, while the later ASR/model wording `phase four test city` canonicalized to `phase_four_test_city`.

The defect was recorded separately in:

`docs/research/STEP_4_PHASE_4_3_OWNER_ACCEPTANCE_FAILURE_1.md`

The fix uses the mature `number-parser==0.3.2` dependency for bounded spoken-number normalization before canonical predicate construction, rather than custom number-word parsing. Automated regression coverage reproducing `phase 4` -> `phase four` now passes.

## 6. Owner-PC normalization + durable encrypted persistence verification — PASS

After pulling the fix and installing the pinned dependency, the owner machine measured:

```text
DIGIT = phase_4_test_city
WORDS = phase_4_test_city
```

The owner then opened the real production encrypted memory runtime directly, without re-saving the memory, and exact-inspected using the spoken-word form `phase four test city`.

Measured result:

```text
FOUND=True
PREDICATE=phase_4_test_city
VALUE=Sagar
SENSITIVITY=standard
```

This proves:

- the original explicit remember operation durably committed to the real encrypted production database;
- the memory survived a complete JARVIS process restart;
- DPAPI + SQLCipher reopen succeeded on the real owner PC;
- the first voice recall failure was lookup-key normalization only, not persistence loss;
- no re-entry or repair write was needed to recover the stored value.

## 7. Cross-session production voice recall after fix — PASS

After a fresh production `jarvis-voice` process restart with persistent memory still enabled, the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The runtime logged:

`Explicit memory inspect hit | predicate=phase_4_test_city | sensitivity=standard | verification=unverified`

JARVIS replied:

`I remember that your Phase 4 Test City is Sagar.`

This is the first complete production voice proof that a fact explicitly remembered in one voice process is recalled from the canonical encrypted store in a later process/session. No re-save occurred between the original write and this successful recall.

Wake detection, provider conversation, integrated vision, speaker-shadow diagnostics, and return-to-sleep behavior remained usable during the successful recall run.

## 8. Explicit production voice correction — PASS

In a later production voice process, the owner said:

`Jarvis, correct my phase 4 test city memory to Indore.`

The runtime logged a committed correction for canonical predicate `phase_4_test_city`, and JARVIS confirmed that the Phase 4 test city was now set to `Indore`.

This proves the explicit correction operation reached the canonical durable lifecycle rather than merely changing transient conversation state.

## 9. Cross-session corrected-value recall — PASS

After another full production process restart, the owner asked for the same memory again and JARVIS answered `Indore`.

The owner reported this run as passing. The pasted console output encountered a separate transcript/paste handling error after the fact, but the human-observed acceptance result was clear: the later process returned the corrected current value `Indore`, not the superseded value `Sagar`.

This satisfies the Phase 4.3 correction persistence requirement.

For the remaining owner acceptance runs, startup greetings are disabled using the existing `JARVIS_STARTUP_GREETING=false` configuration so test repetitions do not consume unnecessary provider/audio budget.

## 10. Remaining mandatory Phase 4.3 acceptance

Before Phase 4.3 may close, continue the real production voice path and prove at minimum:

1. explicit forget succeeds;
2. a later voice session no longer returns the forgotten memory;
3. no implicit ordinary statement is durably stored;
4. no secret/credential request is accepted;
5. normal wake/audio/provider behavior remains usable.

Phase 4.4 remains blocked until this owner cross-session voice acceptance passes.
