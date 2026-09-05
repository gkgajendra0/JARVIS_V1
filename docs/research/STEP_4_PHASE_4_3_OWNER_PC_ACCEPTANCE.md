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

**PHASE 4.3 FINAL CLOSURE: PENDING FINAL CI.**

Date: 2026-09-05

This record captures the real JARVIS Windows owner-machine acceptance evidence for the first production persistent-memory rollout. Phase 4.3 is not marked complete in this record until the post-acceptance closure commit also passes the repository quality gates.

## 1. Retained SQLCipher package integrity — PASS

The retained JARVIS SQLCipher 4.17.0 CPython 3.11 Win64 wheel was downloaded from the successful GitHub Actions artifact and installed into the owner machine's existing `.venv` only after SHA-256 verification.

Wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Expected SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Owner-machine measured SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Result: **MATCH / PASS**.

Pip reported successful installation of `sqlcipher3-0.6.2+jarvis.sqlcipher4170`.

## 2. Production encrypted-memory adapter smoke — PASS

The owner machine ran `tools/research/step4_sqlcipher_production_adapter_smoke.py` using the installed retained wheel and the production `SqlCipherMemoryDatabaseFactory` + Windows DPAPI boundary.

Measured runtime:

- SQLCipher: `4.17.0 community`;
- SQLite: `3.53.3`;
- result: `PASS`;
- leaks: `[]`.

Every production-adapter assertion passed:

- cipher status/version;
- SQLite version;
- migration ledger/version;
- FTS first-open synchronization;
- encrypted reopen current assertion;
- encrypted reopen FTS;
- DPAPI-protected key sidecar exists;
- stdlib plaintext SQLite open blocked;
- synthetic marker absent from storage artifacts.

The smoke used a disposable owner-PC temporary directory under `%TEMP%`; it did not write the real personal-memory database.

## 3. First real voice remember — PASS

With `JARVIS_MEMORY_ENABLED=true`, the normal production voice runtime started without changing provider-native turn detection or the accepted Step-3 audio/vision architecture.

The owner explicitly said:

`Remember that my phase 4 test city is Sagar.`

JARVIS acknowledged the explicit remember request. The process was then returned to idle and fully stopped.

## 4. First cross-session voice recall — FAIL, ROOT CAUSE FIXED

On a new production process/session, the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The realtime tool attempted predicate `phase_four_test_city` and returned no current memory.

This exposed a deterministic key-normalization defect rather than a storage/encryption failure: the original remembered target canonicalized to `phase_4_test_city`, while the later ASR/model wording `phase four test city` canonicalized to `phase_four_test_city`.

The defect was recorded separately in `docs/research/STEP_4_PHASE_4_3_OWNER_ACCEPTANCE_FAILURE_1.md`.

The fix uses the mature `number-parser==0.3.2` dependency for bounded spoken-number normalization before canonical predicate construction rather than custom number-word parsing. Automated regression coverage reproducing `phase 4` -> `phase four` passes.

## 5. Owner-PC normalization + durable encrypted persistence verification — PASS

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

This proves the original explicit remember operation durably committed to the real encrypted production database, survived a complete process restart, reopened successfully through DPAPI + SQLCipher, and required no repair write.

## 6. Cross-session production voice recall after fix — PASS

After a fresh production `jarvis-voice` process restart, the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The runtime logged:

`Explicit memory inspect hit | predicate=phase_4_test_city | sensitivity=standard | verification=unverified`

JARVIS replied that the Phase 4 test city was `Sagar`.

This proved production voice recall from the canonical encrypted store across process boundaries.

## 7. Explicit production voice correction — PASS

The owner later said:

`Jarvis, correct my phase 4 test city memory to Indore.`

The runtime logged a committed correction for canonical predicate `phase_4_test_city`, and JARVIS confirmed the Phase 4 test city was now set to `Indore`.

## 8. Cross-session corrected-value recall — PASS

After another full production process restart, the owner asked for the same memory and JARVIS returned `Indore`, not the superseded `Sagar` value.

The owner directly accepted this run as passing. This satisfies the correction persistence requirement.

For the remaining acceptance runs, startup greetings were disabled using the supported `JARVIS_STARTUP_GREETING=false` configuration so repeated test starts did not consume unnecessary provider/audio budget.

## 9. Explicit production voice forget — PASS

In a fresh production process, the owner said:

`Jarvis, forget my phase four test city memory.`

The runtime logged:

`Explicit memory forget committed | predicate=phase_4_test_city`

The mutation log did not echo either the current `Indore` value or the superseded `Sagar` value. JARVIS confirmed the forget operation and returned to local wake detection normally.

This proves the explicit forget request reached the canonical durable lifecycle through the production voice path.

## 10. Cross-process physical forget — PASS

After a complete `jarvis-voice` process restart, the owner asked:

`Jarvis, what do you remember about my phase four test city?`

The exact lookup returned:

`ToolError while executing tool: no current memory for predicate 'phase_4_test_city'`

JARVIS stated that it retained no memory of the Phase 4 test city. Neither `Indore` nor `Sagar` was returned.

This proves the memory remained physically absent after reopening the production encrypted store in a new process rather than merely disappearing from process-local state.

## 11. Implicit ordinary statement admission — REJECTED / PASS

The owner made an ordinary statement without explicit durable-memory authorization:

`Jarvis my phase four ordinary test animal is otter.`

The production runtime rejected the attempted memory mutation with:

`ToolError while executing tool: latest user turn does not explicitly authorize remember`

JARVIS told the owner that an explicit request would be required.

After another complete process restart, the owner asked:

`Jarvis, what do you remember about my phase four ordinary test animal?`

The exact canonical lookup returned:

`ToolError while executing tool: no current memory for predicate 'phase_4_ordinary_test_animal'`

JARVIS did not return `otter`.

This proves both runtime authorization rejection and durable absence across process boundaries while implicit admission remains disabled.

## 12. Credential/secret voice request — REJECTED / PASS

The owner made an explicit remember request containing a clearly synthetic API-key-style credential.

The realtime assistant refused the request and stated that credentials such as API keys cannot be stored. No memory mutation tool was invoked and no commit log was emitted.

This production behavior is consistent with the architecture boundary: the model has no direct canonical durable-write authority, implicit admission is disabled, and durable mutation is available only through the governed memory tool/`MemoryService` path. The deterministic secret guard itself is independently covered by automated tests that force the tool path and reject obvious API-key/credential/OTP/recovery/private-key-style content before write.

No real credential or secret was used during acceptance.

## 13. Stable production behavior remained usable — PASS

Across the acceptance sequence, the normal runtime repeatedly demonstrated:

- Pocket 3 remained the production conversation microphone;
- wake detection remained usable;
- LiveKit MediaDevices/WebRTC audio remained active;
- provider conversation remained usable;
- vision remained integrated in SAFE mode;
- CAM++ speaker similarity remained shadow-only;
- LR-ASD active-speaker scoring remained shadow-only;
- neither shadow diagnostic gained authority effect;
- JARVIS repeatedly returned to local wake detection after conversations;
- no production mic-routing workaround to Voicemeeter was introduced.

The acceptance sequence therefore did not require destabilizing the accepted Step-3 production audio/vision architecture.

## 14. Owner acceptance conclusion

The real owner-PC sequence has now proved:

1. approved SQLCipher/DPAPI production adapter works;
2. explicit remember persists across processes;
3. exact inspect recalls across processes;
4. explicit correction replaces current truth;
5. corrected truth persists across processes;
6. explicit forget succeeds without value leakage in mutation metadata;
7. forgotten truth remains absent after encrypted-store reopen;
8. implicit ordinary statements are not durably admitted;
9. explicit synthetic credential-memory requests are rejected;
10. normal wake/audio/provider/vision/return-to-sleep behavior remains usable.

**Owner-PC Phase 4.3 acceptance: PASS.**

Phase 4.4 remains blocked only until the post-acceptance closure commit passes the full repository quality gates and the Phase 4.3 closure documents are reconciled.