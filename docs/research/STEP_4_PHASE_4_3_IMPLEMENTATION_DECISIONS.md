# Step 4 — Phase 4.3 Explicit Memory Operations Implementation Decisions

## Status

**IMPLEMENTATION CONTRACT — ACTIVE AFTER PHASE 4.2 AUTOMATED CLOSURE.**

This contract narrows the owner-approved Step-4 architecture for the first useful cross-session memory experience: explicit remember, correct, forget, and inspect operations. It does not authorize implicit durable admission, model-authored truth, or semantic auto-injection.

## Research-first source check — 2026-09-05

Current authoritative tooling was rechecked immediately before implementation:

- LiveKit Agents function tools use `@function_tool`, infer arguments from Python signatures/docstrings, and provide `RunContext`.
- LiveKit function tools work with realtime agents and are distinct from provider-owned tools.
- Google documents function calling as supported for Gemini 3.1 Flash Live Preview; execution is synchronous, so the model waits for the tool result before continuing.
- OpenAI realtime is supported by the same LiveKit function-tool surface.

The repository already has a proven local tool pattern in `VisionAgentTools`. Therefore Phase 4.3 uses LiveKit function tools rather than adding another agent/tool framework.

General-purpose source-code secret scanners such as detect-secrets/gitleaks were considered for credential defense. They are valuable repository scanners but are not selected as a runtime natural-language memory policy engine. The first explicit-memory path uses a narrow fail-closed JARVIS credential guard, with broader adversarial secret testing retained for Phase 4.8.

## 1. Authority boundary

An LLM tool call is **not** proof that the owner explicitly requested a memory mutation.

Before any durable remember/correct/forget operation, the tool layer must inspect the latest canonical accepted USER turn from `ConversationSession` and require a deterministic explicit operation cue matching the requested tool action.

Canonical mutation flow:

```text
accepted USER turn
    -> model chooses explicit-memory tool
    -> deterministic latest-turn intent guard
    -> deterministic sensitivity/secret guard
    -> MemoryService
    -> SQLCipher canonical mutation
    -> post-operation verification/result
    -> tool returns success
    -> only then may provider acknowledge success
```

This keeps the model as a dispatcher/argument proposer rather than the authority for durable truth.

## 2. `MemoryService` becomes the sole public mutation facade

Phase 4.1 implemented lower-level lifecycle/query primitives. Phase 4.3 adds `MemoryService` above them.

Public explicit-memory operations initially include:

- remember one structured personal assertion;
- correct one unambiguous current assertion;
- forget one unambiguous current assertion;
- inspect one exact current assertion.

Only `MemoryService` is exposed to the voice tool layer. The voice adapter must not call SQL or `MemoryLifecycleService` mutation methods directly.

## 3. Initial explicit-memory scope

To minimize model authority during first rollout, the tool surface fixes:

```text
subject_scope = personal
subject       = owner
```

The model/user supplies a semantic `predicate` key and a value for remember/correct. The service builds canonical normalized text itself.

Initial accepted value type is TEXT. Numeric/boolean/JSON remain available in the lower domain but are not necessary for first voice acceptance.

Exact current lookup is by `(personal, owner, predicate)`. Correct/forget fail closed when zero or multiple current assertions match. No fuzzy target resolution is allowed in Phase 4.3.

## 4. Explicit intent guard

The guard is intentionally conservative. False negatives are preferable to false durable writes/deletes.

It recognizes bounded explicit operation language in English/Hindi/Hinglish, including forms equivalent to:

- remember / save this in memory / note this / yaad rakh / याद रख;
- correct / update my memory / change the stored value / that memory is wrong / galat / गलत;
- forget / remove from memory / delete that memory / bhool ja / भूल;
- what do you remember / show my memory / kya yaad hai / क्या याद है.

Negated/discussed/quoted operation phrases must not authorize mutation where deterministic checks can identify them.

If the latest canonical user turn does not explicitly authorize the requested mutation, the tool returns a refusal/result asking the model to request an explicit instruction. It does not write anything.

## 5. Secret-prohibited guard

The runtime must reject attempts to remember obvious credentials or authentication secrets, including explicit references to:

- passwords/passcodes/PINs;
- API keys/access keys/client secrets;
- access/refresh/session tokens;
- OTP/one-time codes;
- recovery/backup codes;
- private keys/seed phrases;
- equivalent Hindi/Hinglish credential terms.

The guard is intentionally conservative and deterministic. It is not claimed to be a complete DLP engine. `SemanticAssertionDraft` already rejects `SECRET_PROHIBITED`; Phase 4.3 prevents obvious credential content from being misclassified as normal/private before constructing the draft.

## 6. Provenance minimization

Explicit memory source records are built from JARVIS canonical provenance, not provider IDs.

For an explicit command:

- `source_class = OWNER_EXPLICIT`;
- `authority_class = OWNER_EXPLICIT`;
- `canonical_ref` references JARVIS `session_id` + `turn_id`;
- `observed_at` comes from canonical `accepted_at`;
- no copied raw utterance in `evidence_text` by default;
- provider `external_item_id` is not required for canonical memory;
- forget command provenance must remain distinct from the target's original provenance.

A forget operation must not retain a fingerprint derived from the forgotten value in ordinary audit metadata.

## 7. Sensitivity

Initial tool arguments may request `standard`, `private`, or `local_only`.

- `standard`: may later cross provider boundary when relevant and allowed;
- `private`: encrypted durable memory, release remains policy-controlled;
- `local_only`: durable local memory that must never cross the provider boundary;
- `secret_prohibited`: cannot be stored and is not exposed as an allowed successful tool choice.

Sensitivity never weakens source authority checks.

## 8. Voice tool surface

Implement one `MemoryAgentTools` object following the established `VisionAgentTools` pattern.

Initial tools:

- remember a text fact/preference by predicate;
- correct an exact stored predicate;
- forget an exact stored predicate;
- inspect an exact stored predicate.

Tool results are structured dictionaries with `ok`, operation/result metadata, and bounded non-secret values where appropriate. Error text must be actionable but must not leak SQL, keys, or internal secrets.

Explicit inspect is read-only and may return an exact eligible current value. It does not invoke semantic retrieval.

## 9. Runtime ownership and storage path

Add a small runtime owner that creates/owns:

```text
%LOCALAPPDATA%/JARVIS/memory.db
%LOCALAPPDATA%/JARVIS/memory.key.dpapi
```

using the existing machine-config root convention, with home-directory fallback already defined by `default_machine_config_path()`.

The runtime owns:

- `WindowsDpapiKeyProtector`;
- `SqlCipherMemoryDatabaseFactory`;
- serialized writer worker;
- serialized reader worker;
- `MemoryLifecycleService`;
- `CanonicalMemoryReader`;
- `MemoryService`;
- clean async close.

There is no plaintext SQLite fallback. If persistent memory is enabled but the approved SQLCipher runtime is unavailable, startup must fail clearly rather than silently pretending memory is persistent.

## 10. Feature rollout

Phase 4.3 persistent memory integration should have an explicit configuration switch while implementation/owner acceptance is underway.

Rules:

- OFF means memory tools are not advertised and no memory database is opened;
- ON means the approved SQLCipher runtime is mandatory;
- do not expose memory tools backed by an in-memory/plaintext substitute in production;
- once owner acceptance is complete, later plan reconciliation may decide the normal default.

## 11. Automated acceptance before owner test

Required tests include:

- `MemoryService` is the only voice-facing mutation facade;
- exact remember -> inspect round trip;
- correction closes inaccurate belief and returns replacement;
- forget physically removes current canonical + FTS representation through the existing lifecycle path;
- ambiguous exact matches fail closed;
- latest canonical USER turn required for mutation authority;
- assistant turn cannot authorize mutation;
- English/Hindi/Hinglish explicit cues;
- negated/discussed phrases do not authorize writes/deletes;
- obvious password/API-key/token/OTP/recovery/private-key requests are rejected;
- source provenance contains JARVIS session/turn refs and does not copy raw utterance text;
- tools return success only after durable service completion;
- no change to provider-native VAD/turn detection;
- memory-disabled runtime exposes no memory tools;
- enabled runtime fails closed when approved SQLCipher is unavailable;
- full existing CI stays green.

After automated validation, a real owner-PC cross-session voice acceptance is mandatory before Phase 4.4 begins.
