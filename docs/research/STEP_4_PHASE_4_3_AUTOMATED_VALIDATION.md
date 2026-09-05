# Step 4 — Phase 4.3 Explicit Memory Automated Validation

## Status

**AUTOMATED VALIDATION: PASS.**

**REAL OWNER-PC CROSS-SESSION VOICE ACCEPTANCE: PASS.**

**PHASE 4.3 FINAL CLOSURE: PASS.**

This record covers the automated implementation gate for explicit `remember`, `correct`, `forget`, and exact `inspect`. It does not authorize implicit durable memory admission, fuzzy/semantic target resolution, model-authored truth, or semantic auto-injection.

## Validated implementation boundary

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

The model may propose a tool call and structured arguments, but neither establishes durable authority by itself.

## Safety properties validated

### Explicit action authority

A mutation requires the latest canonical accepted USER turn to explicitly authorize the matching operation. Assistant output cannot authorize mutation. English, Hindi, and Hinglish bounded cues are covered by deterministic tests.

### Tool-argument grounding

Before exact lookup or mutation, proposed predicates must be named in the latest user utterance after deterministic normalization; remember/correct values must also come directly from that utterance. Missing/implied targets fail closed.

### Durable-facade defense in depth

`MemoryService` independently requires `OWNER_EXPLICIT` source and authority plus source/store sensitivity agreement.

### Secret and release policy

Obvious credential/authentication secrets are rejected before normal durable assertion creation. Allowed initial sensitivity classes are `standard`, `private`, and `local_only`; provider-facing exact inspect does not release `local_only` values. Successful mutation results return bounded metadata and do not echo values.

### Non-rollbackable tool execution

Mutating LiveKit function tools disallow interruption before durable execution so an interrupted generation cannot imply a committed operation was rolled back.

### Exact-target only

Phase 4.3 uses exact `(personal, owner, predicate)` resolution only. Zero or multiple current matches fail closed. No fuzzy or semantic target resolution exists in this phase.

## Runtime rollout boundary

`JARVIS_MEMORY_ENABLED` defaults to `false`.

When disabled, the encrypted runtime is not constructed and no memory tools/database are opened.

When enabled, Windows DPAPI + mandatory `SqlCipherMemoryDatabaseFactory` are used with serialized writer/reader runtime ownership. There is no plaintext SQLite fallback; SQLCipher-open failure fails closed.

Canonical default database location resolves to `%LOCALAPPDATA%/JARVIS/memory.db` on the accepted Windows setup.

## Production voice integration

The stable wake/audio session loop was not rewritten. Normal conversations receive `MemoryAgentTools` bound to their canonical `ConversationSession`; update-approval sessions remain tool-free. Provider-native VAD/turn detection remains unchanged.

## Automated coverage

Coverage includes:

- remember -> inspect -> correct -> inspect -> forget round trip;
- mutation results do not echo durable values;
- latest canonical USER turn required;
- assistant output cannot authorize persistence;
- English/Hindi/Hinglish explicit cues;
- negated/discussed mutation cues rejected;
- predicate/value grounding;
- exact inspect cannot silently change target;
- API-key/credential/OTP/recovery/private-key-style rejection;
- local-only release blocking;
- non-owner-explicit provenance rejection;
- source/store sensitivity mismatch rejection;
- forget re-checks owner authority;
- encrypted runtime start/close ownership;
- enabled runtime fails closed without approved SQLCipher;
- rollout configuration defaults OFF;
- full repository regressions.

## Pre-owner-acceptance CI evidence

Implementation head:

`7451f1e249fa54d687b84ad869ddfa6920509b77`

Code Quality run:

`33959189241`

Results: pytest, Ruff, Windows DPAPI, and Windows Hello all **PASS**.

## Exact SQLCipher owner-PC artifact

Retained SQLCipher workflow run: `33945983433`.

Artifact: `step4-sqlcipher417-cp311-win-amd64`, ID `9963525637`.

Artifact ZIP SHA-256:

`c3df9d2b8ea612921367b5278516b447aba6a27e39688d075dcfdd12b12cb766`

Wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Wheel SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Pinned inputs include SQLCipher commit `810db22f575ee7cf94ea96a3e91622b5fcece3dc`, sqlcipher3 wrapper commit `14fc2632676b20011e0bba64fdda49763a2dd2ec`, SQLCipher 4.17.0 community, SQLite 3.53.3, and OpenSSL recipe 3.6.0.

## Owner-PC gate — PASS

The complete real voice acceptance sequence passed and is recorded in `docs/research/STEP_4_PHASE_4_3_OWNER_PC_ACCEPTANCE.md`.

It proved approved package/runtime operation, cross-process remember/inspect/correct/forget behavior, durable absence after forget, implicit-write rejection, synthetic credential rejection, and stable production voice behavior.

## Final closure CI — PASS

Post-acceptance closure commit:

`69f909d5287d640fa23b7c9206bfef1c0964e70e`

Code Quality run:

`33962138222`

Results:

- pytest: **PASS**;
- Ruff format + lint: **PASS**;
- Windows DPAPI smoke: **PASS**;
- Windows Hello helper build/contract: **PASS**.

**Phase 4.3 automated + owner-PC + final CI acceptance is complete.**