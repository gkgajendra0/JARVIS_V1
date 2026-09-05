# Step 4 — Phase 4.3 Owner-PC Acceptance

## Status

**OWNER-PC PACKAGE + ENCRYPTED ADAPTER: PASS.**

**DURABLE CROSS-PROCESS PERSISTENCE: PASS.**

**CROSS-SESSION VOICE RECALL: PASS.**

**EXPLICIT VOICE CORRECTION: PASS.**

**CROSS-SESSION CORRECTED-VALUE RECALL: PASS.**

**EXPLICIT VOICE FORGET: PASS.**

**CROSS-PROCESS PHYSICAL FORGET: PASS.**

**IMPLICIT-DURABLE-MEMORY REJECTION: PASS.**

**CREDENTIAL/SECRET VOICE REJECTION: PASS.**

**REAL OWNER-PC VOICE ACCEPTANCE: PASS.**

**PHASE 4.3 FINAL CLOSURE: PASS.**

Date: 2026-09-05

This record captures the real JARVIS Windows owner-machine acceptance evidence for the first production persistent-memory rollout.

## 1. Retained SQLCipher package integrity — PASS

Accepted wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Expected and owner-machine SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Result: **MATCH / PASS**.

## 2. Production encrypted-memory adapter smoke — PASS

The owner machine ran `tools/research/step4_sqlcipher_production_adapter_smoke.py` using the retained wheel and production `SqlCipherMemoryDatabaseFactory` + Windows DPAPI boundary.

Measured runtime:

- SQLCipher `4.17.0 community`;
- SQLite `3.53.3`;
- result `PASS`;
- leaks `[]`.

Validated properties included cipher/version checks, migration ledger/version, FTS synchronization, encrypted reopen, DPAPI-protected key material, plaintext stdlib SQLite blocking, and clean storage-marker scan.

## 3. First real voice remember — PASS

With `JARVIS_MEMORY_ENABLED=true`, the owner explicitly said:

`Remember that my phase 4 test city is Sagar.`

JARVIS acknowledged the explicit remember request and the process was fully stopped.

## 4. First cross-session voice recall — FAIL, ROOT CAUSE FIXED

On a new process the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The tool attempted `phase_four_test_city` while the stored key was `phase_4_test_city`.

This was deterministic spoken-number key normalization, not storage loss. The failure is recorded in `docs/research/STEP_4_PHASE_4_3_OWNER_ACCEPTANCE_FAILURE_1.md`.

Research preceded the fix. Mature dependency `number-parser==0.3.2` was selected for bounded spoken-number normalization and the exact owner failure gained regression coverage.

## 5. Durable encrypted persistence after fix — PASS

Without re-saving, the owner directly reopened the real production encrypted memory runtime and measured:

```text
DIGIT = phase_4_test_city
WORDS = phase_4_test_city
FOUND=True
PREDICATE=phase_4_test_city
VALUE=Sagar
SENSITIVITY=standard
```

This proved the first explicit voice remember had persisted correctly across a complete process restart.

## 6. Cross-session voice recall after fix — PASS

After a fresh production process restart, exact inspect hit `phase_4_test_city` and JARVIS returned `Sagar`.

## 7. Explicit voice correction — PASS

The owner said:

`Jarvis, correct my phase 4 test city memory to Indore.`

The runtime committed correction for `phase_4_test_city` and JARVIS confirmed the new current value.

## 8. Cross-session corrected-value recall — PASS

After another full process restart, JARVIS returned `Indore`, not superseded `Sagar`.

## 9. Explicit voice forget — PASS

The owner said:

`Jarvis, forget my phase four test city memory.`

The runtime logged:

`Explicit memory forget committed | predicate=phase_4_test_city`

Mutation metadata did not echo `Indore` or `Sagar`.

## 10. Cross-process physical forget — PASS

After complete restart, the owner asked for the same memory. Exact lookup returned:

`ToolError while executing tool: no current memory for predicate 'phase_4_test_city'`

JARVIS returned neither `Indore` nor `Sagar`.

This proves the memory remained absent after reopening the encrypted store rather than merely disappearing from process-local state.

## 11. Implicit ordinary statement admission — REJECTED / PASS

The owner said, without explicit durable-memory authorization:

`Jarvis my phase four ordinary test animal is otter.`

The runtime rejected the attempted write:

`ToolError while executing tool: latest user turn does not explicitly authorize remember`

After a full restart, exact lookup for `phase_4_ordinary_test_animal` returned no current memory and JARVIS did not return `otter`.

## 12. Credential/secret voice request — REJECTED / PASS

The owner made an explicit remember request containing a clearly synthetic API-key-style credential.

The realtime assistant refused the request and stated that credentials such as API keys cannot be stored. No memory mutation tool was invoked and no commit log was emitted.

This is consistent with the accepted boundary: the model has no direct durable-write authority, implicit admission is disabled, and durable mutation exists only through governed memory tools/`MemoryService`. Automated tests separately force the tool path and prove deterministic credential/secret rejection before write.

No real secret was used.

## 13. Stable production behavior — PASS

Across acceptance runs:

- Pocket 3 remained the production microphone;
- wake detection remained usable;
- LiveKit MediaDevices/WebRTC audio remained active;
- provider conversation remained usable;
- vision remained integrated in SAFE mode;
- CAM++ and LR-ASD remained shadow-only with no authority effect;
- JARVIS repeatedly returned to local wake detection;
- no production mic-routing workaround was introduced.

Startup greetings were disabled only for repeated acceptance runs via supported `JARVIS_STARTUP_GREETING=false`; normal production greeting capability was not removed.

## 14. Final closure CI — PASS

Post-acceptance closure commit:

`69f909d5287d640fa23b7c9206bfef1c0964e70e`

GitHub Actions Code Quality run:

`33962138222`

Result: **SUCCESS**.

Jobs:

- pytest: **PASS**;
- Ruff format + lint: **PASS**;
- Windows DPAPI smoke: **PASS**;
- Windows Hello helper build/contract: **PASS**.

## 15. Conclusion

The real owner-PC sequence proved approved SQLCipher/DPAPI operation, explicit remember/inspect/correct/forget across process boundaries, physical forget, implicit-admission rejection, synthetic credential rejection, and stable production voice behavior.

**Phase 4.3 owner acceptance and closure: PASS.**