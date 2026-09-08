# JARVIS V1 Current Plan

## Active Step

**Step 6 — Knowledge, Current Research, and Truthfulness (CAP-014 through CAP-017) — REQUIREMENTS / RESEARCH NEXT.**

Step 5 is now **bounded complete** after owner-machine acceptance of the deliberately reduced provider-resilience foundation. Full local/offline conversation remains explicitly deferred and is not claimed implemented.

## Current Stage

**STEP 4 BOUNDED COMPLETE — PHASE 4.5E AUTOMATIC MEMORY INFLUENCE DEFERRED — STEP 5 BOUNDED COMPLETE / MINIMAL PROVIDER RESILIENCE ACCEPTED — FULL OFFLINE STEP-5 EXTENSIONS DEFERRED — STEP 6 NEXT**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed evidence belongs in `docs/research/`.

---

## Step 4 closure carried forward

Accepted production behavior remains:

- bounded live session context and deterministic `ContextAssembler`;
- encrypted canonical durable memory with provenance/lifecycle/correction/supersession/physical forget;
- explicit governed `remember`, `inspect`, `correct`, and `forget`;
- structured memory-candidate quarantine with no implicit durable admission;
- accepted Qwen3 Embedding + FTS5/dense/RRF retrieval foundation;
- accepted Qwen3 Reranker over already-eligible canonical records;
- accepted opt-in provider-assisted explicit `recall_memory` fallback;
- deterministic lifecycle/security/sensitivity authority ahead of learned components.

Still deferred / disabled:

- strict independent 4.5D semantic release verifier;
- Phase-4.5E automatic semantic memory influence/injection;
- unaccepted 4.5E shadow-runtime production wiring;
- remaining unstarted Step-4 extensions.

Durable closure evidence:

- `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`
- `docs/research/STEP_4_PHASE_4_5E_DEFERRED_CLOSURE.md`

Automatic memory injection remains disabled. No failed 4.5D/4.5E learned component is promoted.

---

## Step 5 bounded closure — ACCEPTED

The owner deliberately reduced Step 5 to the resilience foundation that is useful now instead of blocking roadmap progress on a full local/offline conversational stack.

### Accepted production behavior

JARVIS now owns deterministic terminal realtime-provider failure diagnosis for bounded classes including:

- quota exhaustion;
- rate limiting;
- authentication failure;
- permission denial;
- model/request rejection;
- provider 5xx/service unavailable;
- timeout;
- network/connection loss;
- unknown terminal provider failure.

For an unrecoverable realtime-provider failure:

```text
LiveKit realtime ErrorEvent
 -> JARVIS deterministic failure classification
 -> ProviderResilienceState = DEGRADED
 -> bounded privacy-safe reason/status metadata
 -> Windows-local deterministic status speech
 -> explicit failed-session close
 -> existing VoiceRuntimeController returns toward wake/idle lifecycle
```

Important boundaries:

- provider/model output does not decide the failure class or recovery authority;
- raw provider payloads are not spoken or copied into normal bounded status logs;
- the failure announcement does not depend on Gemini/OpenAI TTS;
- Windows `System.Speech` synthesizes a fixed JARVIS-owned status message locally;
- local status PCM is played through the already-selected JARVIS audio output;
- no second cloud provider is silently selected;
- no local LLM is loaded;
- no canonical conversation, memory, identity, or authority ownership is duplicated;
- a later healthy realtime session marks provider health recovered.

### Automated acceptance

Final implementation branch includes unit coverage for classification, state transitions, terminal/recoverable error handling, safe close behavior, and local status PCM playback.

Exact-head Code Quality before documentation reconciliation passed:

- Ruff format/lint;
- full pytest;
- Windows DPAPI;
- Windows Hello helper.

### Owner-machine acceptance

Owner-machine smoke on 2026-09-08 used the real configured output:

`24'TV (NVIDIA High Definition Audio) @ 48000 Hz`

Command:

`python tools\research\step5_provider_resilience_owner_smoke.py`

Observed result:

`STEP5_SMOKE_STATUS: PASS`

The owner explicitly confirmed hearing the deterministic local quota-exhaustion message through the real speaker.

Detailed accepted behavior is implemented on PR #23. The smoke harness remains a bounded reproducible owner/regression diagnostic under `tools/research/`.

### Explicitly deferred Step-5 work

The following are **not required for the current bounded Step-5 closure** and remain future work only if they become valuable:

- Ollama/local LLM selection or installation;
- cloud-realtime -> local-LLM automatic handoff;
- local/offline STT;
- local/offline conversational TTS;
- full network-offline spoken conversation;
- cloud-to-cloud automatic failover;
- startup without cloud credentials based on a validated local intelligence stack.

Research already completed for these future options remains in:

- `docs/research/STEP_5_RESILIENCE_RESEARCH_AND_ARCHITECTURE_PROPOSAL.md`

Nothing in the bounded closure claims those deferred capabilities are implemented.

---

## Step 6 — next major development slice

Step 6 owns **Knowledge, Current Research, and Truthfulness (CAP-014 through CAP-017)**.

The next lifecycle begins from current protected `main` after the bounded Step-5 merge:

```text
recover Step-6 requirements
 -> inspect current repo/provider/tool boundaries
 -> fresh current-technology web research
 -> compare mature source/search/research/verification approaches
 -> architecture proposal
 -> owner approval
 -> implementation slices
```

The research-first rule remains mandatory: do not build a custom search/research stack before comparing mature current solutions and the capabilities already available through the active provider/framework ecosystem.

Step 6 must preserve the foundations already accepted:

- one canonical JARVIS conversation/context authority;
- one active production cloud-AI provider policy;
- explicit source/provenance boundaries;
- current/high-risk claims must not be presented as known without appropriate fresh evidence;
- provider/search output is evidence, not canonical personal truth or execution authority;
- Step 6 must not revive automatic Phase-4.5E memory injection as a shortcut.

---

## Immediate Next Action

**Finish final exact-head CI for the bounded Step-5 documentation reconciliation, squash-merge PR #23 into protected `main`, then begin Step-6 requirements recovery + fresh research on a new branch.**

No local model/offline-stack work should interrupt Step 6 unless the owner deliberately reopens the deferred Step-5 scope.
