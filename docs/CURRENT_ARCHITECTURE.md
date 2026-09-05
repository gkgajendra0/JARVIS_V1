# JARVIS V1 Current Architecture

## Status

**STEP 3 COMPLETE + MERGED. STEP 4 MEMORY/CONTEXT ARCHITECTURE IS APPROVED; PHASES 4.0A–4.4 ARE ACCEPTED. PHASE 4.5 SEMANTIC RETRIEVAL IS THE NEXT ACTIVE BOUNDARY. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 REMAINS DISABLED.**

This file describes architecture that actually exists and has passed the normal acceptance lifecycle. Detailed experiments/evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable decisions belong in `docs/decisions/`.

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
        +-> ContextAssembler
              -> bounded evidence-rich provider context
```

Permanent rules:

- identity/perception evidence is not execution permission;
- provider/model output does not establish canonical personal truth;
- `MemoryService` is the sole durable memory mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- production JARVIS has exactly one active cloud-AI provider/account at a time;
- production subsystems may use capability-specific models inside that provider family but may not independently select a second cloud-AI provider;
- implicit memory candidates have no durable authority unless a later separately measured policy is explicitly approved.

Decision: ADR-015.

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

Local model/checkpoint downloads and local inference are outside ADR-015.

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

Accepted machine roles:

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

The accepted Phase-4.4 owner run also proved fail-closed hardware behavior: when Pocket3 was absent from Windows enumeration, startup stopped instead of falling back to a random microphone. After Pocket3 returned in Webcam mode, the stable selector resolved correctly and normal production startup resumed.

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

## Step 4 accepted context/memory ownership

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
    = non-durable semantic shadow only
```

Provider history/caches are never canonical JARVIS memory.

### Provenance and canonical conversation truth

Accepted turns carry stable JARVIS `session_id`, `turn_id`, and aware UTC `accepted_at`. Provider IDs remain external metadata. Assistant output cannot establish durable personal truth.

### LiveContext

Accepted Phase 4.2 runtime maintains bounded in-memory accepted-turn tail, active goal/topic/entities/unresolved work/interaction state, monotonic TTL, and no automatic durable dump. Session disposal does not persist raw conversation state.

### ContextAssembler

`ContextAssembler` applies deterministic precedence, sensitivity release filtering, strict local budget, and immutable JARVIS provenance. It is the sole Step-4 owner of context released toward realtime providers.

Gemini 3.1 realtime mid-session chat-context forwarding remains unsupported/fail-closed in the accepted LiveKit adapter; no automatic provider-history mutation is enabled.

---

## Step 4 canonical encrypted memory kernel

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
- physical forget removes canonical + derived FTS data;
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

Accepted behavior:

- latest canonical USER turn must authorize the matching operation;
- model-proposed predicate/value must be grounded in that turn;
- obvious credentials/authentication secrets are rejected;
- mutation source and authority must be `OWNER_EXPLICIT`;
- source/store sensitivity must agree;
- `local_only` values are not released through provider-facing inspect;
- mutation results do not echo stored values;
- mutating tools disallow interruption during durable execution;
- exact zero/ambiguous targets fail closed;
- spoken-number predicate normalization uses pinned `number-parser==0.3.2`;
- no fuzzy/semantic target selection exists yet;
- implicit ordinary statements are not durably admitted;
- provider history is not used as canonical memory.

Real owner-PC acceptance proved remember, cross-process recall, correction, corrected cross-process recall, physical forget, cross-process absence, implicit-write rejection, and synthetic credential rejection.

---

## Phase 4.4 candidate extraction / quarantine — ACCEPTED

Accepted boundary:

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
- exact accepted turn object is used; no asynchronous latest-turn race;
- non-USER sources do not enter the personal-memory extractor path;
- explicit Phase-4.3 memory operations remain on their governed path;
- provider/model proposes semantic evidence only;
- JARVIS owns provenance and authority metadata;
- no confidence threshold grants truth;
- no candidate writes `MemoryService`, SQLCipher, FTS, or embeddings;
- no implicit durable admission exists;
- quarantine is physically discarded with the session;
- ordinary personal facts do not invoke explicit `remember_memory` after model-facing routing hardening;
- ordinary personal facts do not expose candidate/quarantine mechanics or ask for memory confirmation;
- extraction uses the same active cloud-AI provider selected for JARVIS production.

Measured Gemini 3.5 Flash-Lite corpus result:

- 14/14 schema-valid;
- 100% intent/type/durable core exact;
- zero false durable proposals;
- zero misses;
- English/Hindi/Hinglish accepted;
- p50 ~1.636 s, p95/max ~2.415 s.

Real owner-PC production acceptance proved:

- implicit fact -> `outcome=quarantined`, `durable_admission=False`;
- session close -> `disposed_candidates=1`, `quarantine_disposed=True`;
- fresh explicit memory query -> Phase-4.4 skipped, Phase-4.3 exact lookup miss;
- no cross-session resurrection of the synthetic value;
- wake/Pocket3/Gemini/vision/return-to-wake remained functional;
- CAM++/LR-ASD/prototype/authority behavior remained unchanged.

Evidence:

- `docs/research/STEP_4_PHASE_4_4_GEMINI_MODEL_SELECTION.md`;
- `docs/research/STEP_4_PHASE_4_4_OWNER_PC_ACCEPTANCE.md`;
- `docs/research/STEP_4_PHASE_4_4_IMPLEMENTATION_RESULT.md`.

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

## Next unaccepted architecture

The following remain future Step-4 work and are not current accepted production behavior:

- Phase 4.5 semantic embedding retrieval/reranking and automatic semantic context selection;
- semantic abstention calibration;
- implicit durable candidate admission;
- deterministic canonical subject/predicate normalization for any future implicit admission;
- episodic/reflection learning;
- production self-knowledge registry/aggregation;
- portable memory disaster recovery/export;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-modification.

Phase 4.5 must preserve all existing authority, sensitivity, lifecycle and provider boundaries. Retrieval may rank eligible canonical records; it may not establish or mutate truth.
