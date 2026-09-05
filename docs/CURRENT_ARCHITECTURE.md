# JARVIS V1 Current Architecture

## Status

**STEP 3 COMPLETE + MERGED. STEP 4 MEMORY/CONTEXT ARCHITECTURE IS APPROVED; PHASES 4.0A–4.3 ARE ACCEPTED AND PHASE 4.4 IS ACTIVE. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 REMAINS DISABLED.**

This file describes architecture that actually exists and has passed the normal acceptance lifecycle, plus clearly marked active Step-4 boundaries that are already implemented but not yet finally accepted. Detailed experiments/evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable decisions belong in `docs/decisions/`.

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
        +-> Phase-4.4 candidate extraction [ACTIVE, default OFF]
        |     -> exact canonical USER turn
        |     -> deterministic pre-provider gates
        |     -> active-provider structured-output model
        |     -> typed session-local quarantine
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
- production subsystems may use capability-specific models inside that provider family but may not independently select a second cloud-AI provider.

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

Current supported provider families are `gemini` and `openai`. The provider-to-secret mapping is owned centrally by `src/jarvis/ai_provider.py`; provider-specific SDKs remain confined to narrow voice/memory adapter modules.

Different model IDs are allowed inside the active provider family because capability surfaces differ. This does **not** create a second provider account. Production never silently falls back to another cloud-AI provider when the active provider lacks a capability.

`JARVIS_REALTIME_PROVIDER` is a migration-only alias for existing machine profiles. New configuration uses `JARVIS_AI_PROVIDER`.

Research harnesses may compare providers, but research comparison is not a production dependency.

Pinned model/checkpoint downloads, Git/GitHub traffic, Hugging Face/Google Storage/OpenVINO artifact retrieval, and local inference are not cloud-AI provider selection and are outside ADR-015.

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
- provider-specific model IDs may remain configured for reversible provider switching;
- LR-ASD/CAM++ assets locally managed;
- vision/speaker/active-speaker switches persisted;
- persistent memory rollout controlled by `JARVIS_MEMORY_ENABLED` and defaults OFF.

API keys remain outside normal machine-profile state. Startup preflight checks only the credential required by the selected active provider.

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

## Phase 4.3 explicit durable memory operations

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

## Phase 4.4 active candidate-extraction boundary

Phase 4.4 is implemented behind a default-OFF rollout gate but is not yet finally owner-accepted.

```text
exact accepted canonical USER turn
 -> explicit-memory-control exclusion
 -> deterministic obvious-secret prefilter
 -> active-provider structured-output adapter
 -> Pydantic MemoryExtractionProposal
 -> deterministic proposal policy
 -> session/process-local quarantine
 -> dispose on session close
```

Current invariants:

- extraction runs off the conversation response path;
- no raw/latest-turn race is allowed;
- non-USER sources do not enter the provider extractor path;
- provider/model proposes semantic evidence only;
- JARVIS owns session/turn provenance and authority metadata;
- no confidence threshold grants truth;
- no candidate writes `MemoryService`, SQLCipher, FTS, or embeddings;
- no implicit durable admission exists;
- candidate quarantine is physically discarded with the session;
- extraction uses the same active cloud-AI provider selected for JARVIS production, although its capability-specific model ID may differ.

Final active-provider model validation and narrow owner-PC acceptance remain pending before Phase 4.4 can be marked complete.

---

## Privacy / observability boundary

- raw biometric audio/video is memory-only by default;
- raw full conversation transcripts/provider payloads are not archived merely because available;
- bounded encrypted biometric templates exist only through explicit enrollment;
- secrets/tokens are not normal logs/model context or durable memory;
- successful memory mutations log bounded operation metadata rather than values;
- diagnostic model outputs cannot silently change authority;
- failures and insufficient evidence remain explicit.

---

## Not yet accepted architecture

The following remain future Step-4 work and are not current accepted production behavior:

- Phase 4.4 final provider-local model selection and owner acceptance;
- implicit durable candidate admission;
- semantic embedding retrieval/reranking and automatic semantic injection;
- episodic/reflection learning;
- production self-knowledge registry/aggregation;
- portable memory disaster recovery/export;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-modification.

Phase 4.4 may propose typed candidates, but candidate extraction must not silently become canonical durable truth.
