# JARVIS V1 Current Architecture

## Status

**STEP 3 COMPLETE + MERGED. STEP 4 IS CLOSED AS A BOUNDED ACCEPTED FOUNDATION THROUGH PHASE 4.5C. PHASE 4.5D SEMANTIC RELEASE/ANSWERABILITY AND PHASE 4.5E AUTOMATIC CONVERSATIONAL SEMANTIC MEMORY INJECTION ARE DEFERRED / NOT ACCEPTED. STEP 5 IS PLANNED BUT NOT STARTED. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 REMAINS DISABLED.**

This file describes architecture that actually exists and has passed the accepted lifecycle. Detailed experiments/evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable decisions belong in `docs/decisions/`.

---

## Accepted top-level architecture

```text
                               JARVIS V1
                                   |
                 one active cloud-AI provider/account
                    (Gemini OR OpenAI, never both
                      as production dependencies)
                                   |
          +------------------------+------------------------+
          |                        |                        |
        VOICE                    VISION                  AUTHORITY
          |                        |                        |
Pocket3 microphone          Pocket3 video            typed evidence
          |                        |                        |
LiveKit MediaDevices        OpenCV camera            deterministic trust
AEC + NS + HPF + AGC             |                        |
          |                 RF-DETR + OC-SORT          proposal/risk/policy
          |                        |                        |
active-provider realtime    head/face/liveness       approvals / Windows Hello
          |                        |                        |
NVIDIA 48 kHz -> TV          OWNER context                 |
          |                        |                        |
          +---- CAM++ speaker shadow ----+                 |
          |                              |                 |
          +---- LR-ASD active speaker ---+--- evidence ----+

accepted USER turns
        |
        +-> LiveContext (RAM/session/TTL)
        |
        +-> explicit MemoryAgentTools
        |     -> deterministic authorization/grounding/secret policy
        |     -> MemoryService
        |     -> MemoryLifecycleService
        |     -> SQLCipher canonical store + FTS5
        |
        +-> Phase-4.4 candidate extraction [ACCEPTED, opt-in]
        |     -> exact canonical USER turn
        |     -> deterministic pre-provider gates
        |     -> Gemini 3.5 Flash-Lite structured proposal
        |     -> deterministic JARVIS proposal policy
        |     -> typed session-local quarantine
        |     -> physical disposal on session close
        |     X no durable admission
        |
        +-> Phase-4.5A–4.5C derived retrieval foundation [ACCEPTED]
        |     -> eligible canonical records only
        |     -> FTS5 lexical rank + Qwen dense rank
        |     -> equal-weight RRF
        |     -> Qwen reranker
        |     X does not establish truth
        |     X not automatically released to Gemini conversation
        |
        +-> ContextAssembler
              -> bounded evidence-rich provider context
              -> no automatic 4.5D/4.5E semantic-memory release
```

Permanent rules:

- identity/perception evidence is not execution permission;
- provider/model output does not establish canonical personal truth;
- `MemoryService` is the sole durable memory mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- production JARVIS has exactly one active cloud-AI provider/account at a time;
- production subsystems may use capability-specific models inside that provider family but may not independently select a second cloud-AI provider;
- local model/checkpoint inference does not gain canonical truth or authority merely because it is local;
- retrieval ranks already-eligible canonical records and cannot establish, modify, resurrect, or forget truth;
- implicit memory candidates have no durable authority;
- automatic semantic memory release remains disabled until a future separately accepted boundary exists.

Decision: ADR-015 governs cloud-provider ownership.

---

## Cloud-AI provider ownership

Production cloud intelligence is selected once through `JARVIS_AI_PROVIDER`.

```text
JARVIS_AI_PROVIDER
       |
       +-> realtime conversation
       +-> scripted cloud TTS
       +-> structured memory-candidate extraction
       +-> future cloud reasoning/tool roles
```

Current active provider is Gemini. Realtime conversation and structured extraction may use different Gemini model IDs because their capability surfaces differ. This does not create a second provider account.

Provider-specific SDKs remain confined to narrow adapters. `JARVIS_REALTIME_PROVIDER` is migration-only compatibility; new configuration uses `JARVIS_AI_PROVIDER`.

Production never silently falls back to another cloud-AI provider when the active provider lacks a capability.

Local model/checkpoint downloads and local inference are outside ADR-015 but remain bounded by JARVIS deterministic authority and truth rules.

---

## Machine configuration and startup

Normal startup remains machine-profile driven:

```text
%LOCALAPPDATA%\JARVIS\machine.json
        +
Windows environment for the active provider secret
        -> startup preflight
        -> jarvis-voice
```

Accepted machine roles include:

- Pocket3 microphone selected by stable Windows WASAPI identity;
- NVIDIA `24'TV` conversation output at 48 kHz;
- local wake model path persisted;
- one active cloud-AI provider persisted as `JARVIS_AI_PROVIDER`;
- provider-specific model IDs explicitly configured where needed;
- LR-ASD/CAM++ assets locally managed;
- vision/speaker/active-speaker switches persisted;
- persistent memory controlled by `JARVIS_MEMORY_ENABLED`;
- candidate extraction controlled separately by `JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED` plus explicit model ID.

API keys remain outside normal machine-profile state. Startup preflight checks only the credential required by the selected active provider.

Fail-closed hardware behavior remains accepted: if the configured Pocket3 device is absent, startup does not silently choose a random microphone.

---

## Conversation audio — one production microphone owner

```text
Pocket3 microphone @ 48 kHz mono
        -> LiveKit rtc.MediaDevices.open_input()
        -> WebRTC AEC + NS + HPF + AGC
        -> canonical processed user PCM
              +-> wake / AgentSession / realtime conversation
              +-> CAM++ speaker shadow
              +-> LR-ASD audio input
        -> LiveKit MediaDevices output / APM render reference
        -> NVIDIA HDMI @ 48 kHz -> 24'TV
```

LiveKit MediaDevices remains the only production Pocket3 microphone owner. Speaker/active-speaker diagnostics reuse canonical PCM and never gain permission authority.

Decisions: ADR-011, ADR-013, ADR-014.

---

## Vision / OWNER evidence

```text
Pocket3 video
 -> OpenCVCameraSource + monotonic CapturedFrame
 -> RF-DETR person detection
 -> OC-SORT persistent track
 -> head association
 -> YuNet + SFace OWNER identity
 + MiniFAS passive liveness
 + active-liveness fallback when required
 -> same Windows session + same visual track
 -> OWNER-context evidence
```

OWNER visual evidence remains freshness/session/track-bound evidence, not permission.

---

## Speaker and active-speaker shadow

CAM++ uses canonical LiveKit PCM, bounded turn capture, local speech/quality gating, encrypted OWNER prototypes, and diagnostic similarity only.

LR-ASD combines canonical LiveKit user PCM with timestamped normal Vision OWNER/head frames. No production threshold is selected. `active_speaker_confirmed` remains false and prototype admission remains disabled.

Neither CAM++ nor LR-ASD changes authority.

---

## Authority architecture

```text
identity/context evidence
 -> graduated trust
 -> immutable ActionProposal
 -> deterministic risk floor
 -> fail-closed OPA policy
 -> proposal-bound approval / strong verification
 -> final revalidation
 -> one-time execution permit
 -> execution result + privacy-aware audit
```

Accepted trust vocabulary:

- T0 `UNVERIFIED`
- T1 `PRESENT_CONTEXT`
- T2 `CORROBORATED_OWNER`
- T3 `VERIFIED_OWNER`

**T2 remains disabled.** Windows Hello remains the accepted strong-verification path.

---

# Step 4 accepted bounded architecture

## Ownership model

```text
ConversationSession
    = canonical accepted conversation truth

LiveContext
    = current session/working context only

MemoryService
    = sole durable memory mutation/truth facade

MemoryLifecycleService
    = canonical temporal lifecycle implementation

ContextAssembler
    = sole Step-4 provider-context release owner

SQLCipher + SQLite
    = canonical durable memory store

FTS5
    = derived/rebuildable lexical index

MemoryCandidateSessionRuntime
    = non-durable semantic shadow/quarantine

Derived vector index / retrieval stack
    = rebuildable ranking data over already-eligible canonical records
```

Provider history/caches are never canonical JARVIS memory.

### Provenance and canonical conversation truth

Accepted turns carry stable JARVIS `session_id`, `turn_id`, and aware UTC `accepted_at`. Provider IDs remain external metadata. Assistant output cannot establish durable personal truth.

### LiveContext

The accepted runtime maintains bounded in-memory accepted-turn tail, active goal/topic/entities/unresolved work/interaction state, monotonic TTL, and no automatic durable dump. Session disposal does not persist raw conversation state.

### ContextAssembler

`ContextAssembler` applies deterministic precedence, sensitivity release filtering, strict local budget, and immutable JARVIS provenance. It is the sole Step-4 owner of context released toward realtime providers.

Automatic semantic-memory retrieval results from the 4.5A–4.5C foundation are **not** released through `ContextAssembler` merely because they can be ranked.

---

## Canonical encrypted memory kernel — ACCEPTED

```text
MemoryService
 -> MemoryLifecycleService
 -> serialized SQLCipher writer / dedicated reader
 -> ordered checksum-validated migrations
 -> canonical temporal relational assertions
 -> FTS5 derived lexical index
```

Accepted storage/security properties:

- SQLCipher 4.17.0 Community;
- accepted SQLite baseline 3.53.3;
- random 32-byte DB key;
- Windows DPAPI user-scope protection + purpose binding;
- no plaintext key file;
- no plaintext SQLite fallback when memory is enabled;
- physical forget removes canonical and derived data;
- exact current queries are deterministic;
- database/key material lives under the approved local machine boundary, normally `%LOCALAPPDATA%\JARVIS\memory.db` plus protected key material.

---

## Phase 4.3 explicit durable memory operations — ACCEPTED

Normal voice sessions may expose four governed memory tools when persistent memory is enabled:

```text
remember
inspect
correct
forget
```

The durable path is:

```text
latest canonical accepted USER turn
 -> LiveKit memory function tool
 -> explicit-action authorization
 -> predicate/value grounding
 -> secret/sensitivity policy
 -> OWNER_EXPLICIT provenance/authority
 -> MemoryService
 -> encrypted canonical lifecycle
```

Accepted invariants include:

- latest canonical USER turn must authorize the matching operation;
- model-proposed predicate/value must be grounded in that turn;
- obvious credentials/authentication secrets are rejected;
- mutation source and authority must be `OWNER_EXPLICIT`;
- source/store sensitivity must agree;
- `local_only` values are not released through provider-facing inspect;
- mutation results do not echo stored values;
- exact zero/ambiguous targets fail closed;
- no implicit ordinary statement becomes durable memory.

---

## Phase 4.4 candidate extraction / quarantine — ACCEPTED

```text
exact accepted canonical USER turn
 -> explicit-memory-control exclusion
 -> deterministic obvious-secret prefilter
 -> active-provider structured-output adapter
 -> Gemini 3.5 Flash-Lite
 -> Pydantic MemoryExtractionProposal
 -> deterministic proposal policy
 -> session/process-local quarantine
 -> physical disposal on session close
```

Accepted invariants:

- extraction runs off the conversation response path;
- exact accepted USER turn object is used;
- provider/model proposes semantic evidence only;
- JARVIS owns provenance and authority metadata;
- no confidence threshold grants truth;
- no candidate writes `MemoryService`, SQLCipher, FTS, or embeddings;
- no implicit durable admission exists;
- quarantine is physically discarded with the session;
- extraction uses the same active cloud-AI provider selected for JARVIS production.

Detailed measured evidence remains in `docs/research/STEP_4_PHASE_4_4_*`.

---

## Phase 4.5A–4.5C derived semantic retrieval foundation — ACCEPTED

The accepted derived stack operates only over records that have already passed canonical lifecycle/security/sensitivity eligibility.

### Embedding

`Qwen/Qwen3-Embedding-0.6B`

- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256-dimensional embedding contract;
- exact local cosine comparison;
- derived vectors remain rebuildable and non-canonical.

### First-stage retrieval

```text
eligible canonical records
       +-> SQLite FTS5 lexical rank
       +-> Qwen dense rank
       -> equal-weight reciprocal-rank fusion (k=60)
```

### Reranking

`Qwen/Qwen3-Reranker-0.6B`

- revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- BF16 accepted owner path;
- deterministic tie handling.

Accepted owner stack:

- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`;
- Transformers `5.16.1`;
- SentenceTransformers `6.0.1`;
- NVIDIA GeForce RTX 5060 Ti 8 GB.

This stack answers **which eligible records are related/rank highly**. It does not answer whether a record is semantically sufficient or appropriate for the exact user question.

---

## Phase 4.5D semantic release authority — DEFERRED / NOT ACCEPTED

The unresolved boundary is:

```text
user question
 + candidate canonical memory
 -> determine whether this exact fact may answer this requested semantic role
 -> release or abstain
```

Research and owner evidence showed that the tested generic QA, NLI-abstention, frozen-embedding classifier, and zero-shot question-role approaches did not meet the zero-unsafe-release / multilingual recall requirements.

Therefore:

- no 4.5D learned guard is production-selected;
- no confidence threshold is fitted on exposed failure corpora;
- no safety gate is weakened;
- no automatic semantic release is enabled;
- exact retired evidence remains documented under `docs/research/`;
- closure rationale is `docs/research/STEP_4_PHASE_4_5D_DEFERRED_CLOSURE.md`.

Native multilingual NLI evidence may be reconsidered in a future architecture only as a downstream YES/NO truth evaluator **after** answerability has been established independently; it is not an abstention authority.

---

## Phase 4.5E and remaining Step-4 extensions — DEFERRED

Normal conversational semantic-memory injection is not accepted. The presence of the 4.5A–4.5C retrieval stack does not authorize provider-facing injection.

The remaining unstarted Step-4 extensions are deferred with the bounded closure so later roadmap steps can proceed without pretending the unresolved semantic release boundary is solved.

---

## Privacy / observability boundary

- raw biometric audio/video is memory-only by default;
- raw full conversation transcripts/provider payloads are not archived merely because available;
- bounded encrypted biometric templates exist only through explicit enrollment;
- secrets/tokens are not normal logs/model context or durable memory;
- successful memory mutations log bounded operation metadata rather than values;
- candidate shadow logs bounded outcomes/reasons/counts rather than candidate values;
- diagnostic model outputs cannot silently change authority;
- failures and insufficient evidence remain explicit.

---

## Explicitly not accepted / deferred

The following are not current production behavior:

- automatic semantic memory release into normal Gemini conversation;
- a production 4.5D answerability/semantic-role guard;
- implicit durable candidate admission;
- autonomous episodic/reflection learning;
- production self-knowledge registry/aggregation;
- portable memory disaster recovery/export;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-modification.

Any future reopening of semantic conversational memory must preserve all accepted authority, sensitivity, lifecycle, provider, and canonical-truth boundaries and must use fresh never-exposed evidence.
