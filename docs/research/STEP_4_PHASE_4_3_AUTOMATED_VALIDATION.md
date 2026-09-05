# Step 4 — Phase 4.3 Explicit Memory Automated Validation

## Status

**AUTOMATED VALIDATION: PASS.**

**REAL OWNER-PC CROSS-SESSION VOICE ACCEPTANCE: PENDING.**

Phase 4.3 is not complete until the exact approved SQLCipher 4.17 Windows package and the integrated realtime voice path pass on the real JARVIS PC.

This record covers only the automated implementation gate for explicit `remember`, `correct`, `forget`, and exact `inspect`. It does not authorize implicit durable memory admission, fuzzy/semantic target resolution, model-authored truth, or semantic auto-injection.

## Validated implementation boundary

The implemented path is:

```text
latest canonical accepted USER turn
        |
        v
LiveKit function tool dispatch
        |
        +-> deterministic explicit-action authorization
        +-> deterministic predicate/value grounding
        +-> deterministic secret/sensitivity policy
        |
        v
MemoryService
sole public durable mutation facade
        |
        v
MemoryLifecycleService
        |
        v
SQLCipher canonical store + FTS5
```

The model may propose a tool call and structured arguments, but neither the tool call nor model-generated arguments establish durable authority by themselves.

## Safety properties now enforced

### Explicit action authority

A mutation requires the latest canonical accepted USER turn to explicitly authorize the matching operation. Assistant output cannot authorize a mutation.

English, Hindi, and Hinglish bounded cues are covered by deterministic tests. Negated/discussed operation phrases fail closed where the current deterministic guard can identify them.

### Tool-argument grounding

The realtime model supplies tool arguments, so Phase 4.3 does not trust them merely because they satisfy the function schema.

Before exact lookup or mutation:

- the proposed predicate must be directly named in the latest user utterance after deterministic Unicode-aware normalization;
- remember/correct values must also be directly present in the latest user utterance;
- missing/implied targets fail closed and require the user to state the exact memory target rather than letting the model guess.

This deliberately prefers false negatives over accidental durable writes/deletes during the first rollout.

### Durable-facade defense in depth

`MemoryService` independently requires:

- `MemorySourceClass.OWNER_EXPLICIT`;
- `AuthorityClass.OWNER_EXPLICIT`;
- source sensitivity equal to the stored memory sensitivity.

This protects the durable boundary even if a future caller bypasses the voice-tool authorization layer.

### Secret and release policy

Obvious credential/authentication secrets are rejected before constructing a normal durable assertion.

Initial allowed sensitivity classes are `standard`, `private`, and `local_only`. `local_only` exact inspect does not return the stored value through the provider-facing tool result.

Successful mutation tool results return bounded operation metadata and do not echo the stored value.

### Non-rollbackable tool execution

Mutating LiveKit function tools call `RunContext.disallow_interruptions()` before durable execution so an interrupted generation cannot misleadingly imply that a committed write/delete was rolled back.

### Exact-target only

Phase 4.3 uses exact `(personal, owner, predicate)` resolution only. Zero or multiple current matches fail closed. No fuzzy or semantic target resolution exists in this phase.

## Runtime rollout boundary

`JARVIS_MEMORY_ENABLED` is an explicit persisted/non-secret rollout setting and defaults to `false`.

When disabled:

- the encrypted memory runtime is not constructed;
- no persistent memory database is opened;
- memory tools are not added to normal voice sessions.

When enabled:

- the runtime owns a Windows DPAPI protector;
- `SqlCipherMemoryDatabaseFactory` is mandatory;
- one serialized writer worker and one reader worker are started before voice runtime execution;
- there is no plaintext SQLite fallback;
- failure to open the approved SQLCipher runtime fails the enabled memory startup rather than pretending persistence succeeded.

Canonical default database location follows the machine-config root and resolves to `%LOCALAPPDATA%/JARVIS/memory.db` on the accepted Windows setup, with the existing home-directory fallback where `LOCALAPPDATA` is unavailable.

## Production voice integration

The stable base wake/audio session loop was not rewritten for Phase 4.3.

`CanonicalActiveSpeakerRuntimeController` wraps the existing session factory to capture the canonical `ConversationSession` and composes per-session `MemoryAgentTools` with the already-existing vision tool surface. The update-approval session still starts with `tools=[]`, while each normal conversation receives tools bound to its own canonical conversation truth.

Provider-native VAD/turn detection remains unchanged.

## Automated tests added

Automated coverage now includes:

- explicit remember -> exact inspect -> correction -> exact inspect -> forget round trip;
- mutation result does not echo the durable value;
- latest canonical USER turn required for mutation authority;
- assistant output cannot authorize persistence;
- English/Hindi/Hinglish explicit action cues;
- negated/discussed mutation cues rejected;
- model-proposed predicate must be grounded in the latest user utterance;
- model-proposed remember/correct value must be grounded in the latest user utterance;
- exact inspect cannot switch to a different model-proposed target absent from the user's query;
- obvious credential/API-key/OTP/recovery/private-key-style content rejected before write;
- local-only exact inspect never releases its value to the provider-facing result;
- `MemoryService` rejects non-owner-explicit provenance;
- `MemoryService` rejects source/store sensitivity mismatch;
- forget re-checks owner-explicit authority before physical deletion;
- encrypted memory runtime start/close ownership;
- enabled runtime fails closed when the approved SQLCipher driver is unavailable;
- memory rollout configuration defaults OFF and validates persisted/environment values;
- full existing repository regressions remain green.

## Final automated CI evidence

Implementation head:

`7451f1e249fa54d687b84ad869ddfa6920509b77`

GitHub Actions Code Quality run:

`33959189241`

Results:

- pytest: **PASS**;
- Ruff format + lint: **PASS**;
- Windows DPAPI smoke: **PASS**;
- Windows Hello helper build/contract: **PASS**.

The immediately preceding argument-grounding implementation run `33959051456` also passed pytest, Windows DPAPI, and Windows Hello; its only failure was a single Ruff formatting change in `memory_tools.py`, corrected before the final run above.

## Exact SQLCipher owner-PC acceptance artifact

The retained successful SQLCipher 4.17 artifact comes from workflow run:

`33945983433`

Artifact:

`step4-sqlcipher417-cp311-win-amd64`

Artifact ID:

`9963525637`

Artifact ZIP SHA-256 reported by GitHub and independently rechecked after retrieval:

`c3df9d2b8ea612921367b5278516b447aba6a27e39688d075dcfdd12b12cb766`

The retained artifact manifest identifies the wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

with SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Pinned build inputs inside that retained artifact:

- SQLCipher commit `810db22f575ee7cf94ea96a3e91622b5fcece3dc`;
- full sqlcipher3 wrapper commit `14fc2632676b20011e0bba64fdda49763a2dd2ec`;
- SQLCipher `4.17.0 community`;
- SQLite `3.53.3`;
- OpenSSL recipe `3.6.0`.

Its included runtime verification reports `PASS`, FTS5 compiled, WAL, memory temp store, secure delete, wrong-key/no-key blocking, corruption detection, forget canonical/FTS zero, leak scans clean, and enhanced `cipher_memory_security=ON` subprocess probe passing.

This retained wheel hash differs from the first earlier substantive research-build hash because the artifact was rebuilt after the upload-plumbing correction. The owner-PC gate must therefore verify the exact retained wheel hash above rather than reuse the earlier one-off build digest.

## Remaining gate

Phase 4.3 now requires real owner-PC acceptance using the exact retained SQLCipher wheel and the normal JARVIS voice runtime.

The acceptance sequence must prove across separate voice sessions:

1. exact retained SQLCipher wheel installs and reports SQLCipher 4.17.0 / SQLite 3.53.3;
2. memory rollout can be enabled without changing provider-native turn detection;
3. explicit remember persists a harmless fact;
4. a new voice session exact-inspects that fact;
5. explicit correction changes current truth;
6. a new session returns only the corrected current value;
7. explicit forget physically removes the current memory;
8. a new session no longer returns the forgotten value;
9. an explicit credential-memory attempt is rejected;
10. no raw full transcript is introduced as durable memory evidence;
11. database/key material is created only under the approved local encrypted boundary.

Only after the owner accepts this behavior may Phase 4.3 be marked complete and Phase 4.4 structured candidate extraction begin.
