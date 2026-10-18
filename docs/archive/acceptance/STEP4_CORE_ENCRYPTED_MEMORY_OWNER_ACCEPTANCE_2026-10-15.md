# Step 4 Core Encrypted Persistent Memory — Owner-Machine Acceptance (2026-10-15)

## Decision

**ACCEPTED / PASSED for core encrypted persistent memory and explicit-memory storage.**

**DEFERRED for end-to-end provider-assisted conversational semantic recall.** Step 4 as a whole remains **BOUNDED**, not fully DONE. Automatic/implicit memory candidate admission and proactive context injection remain disabled and are not approved by this acceptance.

Owner explicitly approved this scoped acceptance on 2026-10-16 based on real Windows evidence from 2026-10-15. This is an acceptance record, not a new feature promotion or permission to enable automatic memory admission.

## Environment and evidence

- Windows owner machine; local repository `main` at **`fbc79c6d1695421a9674a58e9ec2a5810cd29351`** after PR #258.
- Python **3.11.9** in the JARVIS `.venv`; custom `sqlcipher3` wheel **`0.6.2+jarvis.sqlcipher4170`** installed.
- Actual runtime engines: SQLCipher **4.17.0 community** and SQLite **3.53.3**.
- The corrected `tools/research/step4_sqlcipher_production_adapter_smoke.py` passed **12/12 checks** on the owner machine. These include encryption status, version pins, schema migration version 2 with two migration ledger entries, semantic retrieval schema, full-text search before/after reopen, protected Windows DPAPI key, rejection of plaintext SQLite opening, and no visible test marker in on-disk database/key artifacts.
- Voice preflight passed after changing the configured output from the disconnected 24-inch TV to the ASUS VG34WQML5A using Windows WASAPI. Wake, microphone, playback, camera and production runtime initialized. Log reported: `JARVIS explicit persistent memory is active; implicit admission remains disabled`.
- User explicitly said **"Remember that my memory test token is Blue Comet 47."** Production voice log: `Explicit memory remember committed | predicate=memory_test_token`; assistant acknowledged save.
- Jarvis was shut down and relaunched. An independent, read-only production-memory service query against the *existing* encrypted memory store using `inspect_exact(predicate="memory_test_token")` returned **`RESULT: MEMORY FOUND`**, `Stored value: Blue Comet 47`. This confirms durable persistence across process restart and deterministic production-service retrieval, not merely a temporary synthetic database.

## Deferred scope and reason

**Natural-language semantic recall from the realtime voice session is NOT accepted by this evidence.**

- The Gemini `gemini-3.8-flash` provider-assisted recall path requires external structured planning and same-provider verification. Owner runtime logs showed Google Interactions API **HTTP 503 Service Unavailable**, and a later session showed **HTTP 429 Too Many Requests**. The owner reports Gemini paid billing/quota is not enabled. **429 is consistent with rate/quota pressure; 503 indicates an unavailable service and is not independently proof of quota exhaustion.**
- The attempted explicit voice `inspect_memory` flow did not prove voice retrieval either: one request returned `user turn does not explicitly authorize inspect`; the assistant then refused to reveal information containing a “token.” Thus a tool authorization/wording issue is separately observed and must not be silently categorized as only Gemini quota.
- No confirmed successful provider-verified semantic recall and spoken correct answer after restart appears in the acceptance evidence. Fail-closed abstention is desirable, but availability and user experience are still unproven.
- The pending check should be run with available, authorized provider quota: explicit voice inspect with an unambiguous non-secret test-memory label, natural-language `recall_memory`, confirmation of exact retrieved answer and authorization-policy behavior, with no bypass of sensitivity/Authority/release gates.

## Scope boundaries

- Accept **SQLCipher Windows packaging, production encryption and DPAPI key protection, explicit durable voice write, persistence after restart, and deterministic production-memory-service read**.
- Do **not** claim the owner-machine check proves successful end-to-end cloud semantic recall, automatic learning, memory injection into ordinary prompts, or any new device-control/development capability.
- **PR #252 D7/D8 are unrelated Development Engine acceptance stages** and have not been closed by this Step 4 milestone.
- Defer provider-dependent recall acceptance without blocking unrelated governed development. Do not change provider billing, enable new implicit-memory features or loosen release guards as a shortcut.

## Follow-up acceptance gate

On a later owner-machine run with a healthy authorized structured provider, show a freshly spoken memory request being resolved through the semantic planner, exact canonical retrieval and release verifier, then prove the expected spoken answer after a restart. Separately verify `inspect_memory` owner-turn authorization with a neutral named memory target. Record evidence before upgrading the semantic recall milestone.
