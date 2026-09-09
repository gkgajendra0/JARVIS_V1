# JARVIS V1 Current Architecture

## Status

**STEPS 0–3 ARE COMPLETE. STEP 4 IS BOUNDED COMPLETE. STEP 5 IS BOUNDED COMPLETE. STEP 6 IS BOUNDED COMPLETE. STEP 7 — GOVERNED CAPABILITY RUNTIME + LOCAL FILES/SYSTEM/PROJECT SAFE READS — IS OWNER ACCEPTED AND AT THE FINAL DOCUMENTATION/PROTECTED-MAIN MERGE GATE. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 `CORROBORATED_OWNER` REMAINS DISABLED.**

This file describes architecture that actually exists and has passed the accepted lifecycle. Detailed experiments and acceptance evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable design decisions belong in `docs/decisions/`.

---

## Accepted top-level architecture

```text
                                  JARVIS V1
                                      |
                     one active cloud-AI provider
                      Gemini / OpenAI / replacement
                                      |
        +-----------------------------+-----------------------------+
        |                             |                             |
      VOICE                         VISION                       AUTHORITY
        |                             |                             |
Pocket3 microphone             Pocket3 video                 typed evidence
        |                             |                             |
LiveKit MediaDevices           OpenCV camera                 deterministic trust
AEC + NS + HPF + AGC                |                             |
        |                       RF-DETR + OC-SORT              proposal/risk/policy
        |                             |                             |
active-provider realtime       head/face/liveness            approvals / Windows Hello
        |                             |                             |
NVIDIA 48 kHz -> TV             OWNER context                       |
        |                             |                             |
        +----- CAM++ speaker shadow --+                             |
        +----- LR-ASD active speaker -+--------- evidence ----------+

accepted canonical USER turns
        |
        +-> LiveContext
        |
        +-> explicit durable Memory tools
        |     -> MemoryService / lifecycle
        |     -> SQLCipher + FTS5
        |
        +-> bounded provider-assisted recall_memory
        |
        +-> source-aware search_web
        |     -> CurrentResearchService
        |     -> replaceable retrieval adapter (accepted: Exa)
        |     -> JARVIS-owned provenance/truth/source policy
        |
        +-> governed inspect_local
              -> CapabilityResolver / CapabilityRuntime
              -> canonical AuthorityService
              -> bounded read executor
              -> structured result + provenance + audit
```

The conversational model may reason about which mature capability is useful, but provider/model output does not own JARVIS identity, durable truth, authority, permissions, capability registration, execution policy, or deployment.

---

## Permanent architecture rules

- JARVIS identity/state/truth/authority/capabilities remain provider-neutral and JARVIS-owned.
- Production has exactly one active cloud-AI provider/account at a time.
- Provider-specific SDKs stay behind narrow adapters.
- Identity/perception evidence is not execution permission.
- T2 `CORROBORATED_OWNER` remains disabled until separately validated.
- Windows Hello/T3 remains the accepted strong-verification path.
- CAM++ and LR-ASD remain diagnostic/shadow evidence only and have no authority effect.
- `ConversationSession` owns canonical accepted conversational truth.
- `MemoryService` is the sole durable memory mutation facade.
- Provider/model output cannot directly create canonical personal truth.
- Retrieved web/local content is untrusted evidence/data and gains no memory, policy, identity, or tool authority.
- `AuthorityService` remains the single canonical action-permission path; later capabilities must not invent parallel permissions.
- One-time execution permits are proposal-bound and revalidated immediately before execution.
- No raw discovered CLI/MCP command surface is exposed as arbitrary model-controlled shell authority.
- Later browser/app/device/file-write/coding features must build on the shared capability/authority boundaries rather than bypassing them.

---

## Cloud-AI provider ownership

Production cloud intelligence is selected once through `JARVIS_AI_PROVIDER`.

```text
JARVIS_AI_PROVIDER
       |
       +-> realtime conversation
       +-> scripted cloud TTS where used
       +-> structured memory-candidate extraction
       +-> provider-assisted semantic recall when configured
       +-> source-aware research reasoning
       +-> capability/tool planning
```

Current production provider is Gemini. Different model IDs may be used for capability-specific roles inside that same provider family where the provider surfaces differ.

Production does not silently switch to a second cloud provider when the active provider lacks a feature or reaches quota/rate limits.

Local checkpoint/model inference remains allowed behind JARVIS-owned boundaries but gains no truth or authority merely because it is local.

Decision: ADR-015 governs cloud-provider ownership.

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

The accepted Step-2 long-utterance correction keeps provider-native realtime turn completion authoritative while using local user speech activity only to prevent the outer lifecycle from expiring during active speech or provider/session initialization.

Acceptance evidence: `docs/research/STEP_2_LONG_UTTERANCE_ACTIVITY_ACCEPTANCE.md`.

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

LR-ASD combines canonical LiveKit user PCM with timestamped normal Vision OWNER/head frames. No production admission threshold is selected. `active_speaker_confirmed` remains false and prototype admission remains disabled.

Observed meeting-audio false USER turns during Step-7 acceptance are therefore a known voice/identity admission residual. They do not alter capability authority. Step-7 local-read grounding separately rejects ambiguous turns that do not explicitly warrant local inspection.

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

For Step-7 private local reads, JARVIS intentionally escalates to T3 rather than weakening the existing T2 floor.

Accepted authority properties:

- risk is determined from semantic action/target/effect, not merely a primitive operation name;
- approvals are proposal/fingerprint bound;
- permits are one-time and revalidated immediately before execution;
- authority/audit failure withholds consequential results;
- stronger verification may satisfy lower required trust floors;
- provider/model output never directly grants authority.

Acceptance evidence: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

---

## Step 4 — accepted bounded memory/context architecture

### Ownership model

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
    = sole ordinary provider-context assembly owner

SQLCipher + SQLite
    = canonical durable memory store

FTS5
    = derived/rebuildable lexical index

MemoryCandidateSessionRuntime
    = non-durable semantic shadow/quarantine

Derived retrieval stack
    = rebuildable ranking data over already-eligible canonical records

ProviderVerifiedMemoryQueryCoordinator
    = bounded opt-in semantic recall coordinator; no mutation authority
```

Accepted durable storage/security properties include SQLCipher, Windows DPAPI user-scope key protection, no plaintext fallback when memory is enabled, explicit remember/inspect/correct/forget, canonical temporal lifecycle, and physical forgetting of canonical/derived data.

Phase-4.4 candidate extraction remains session-local quarantine with no implicit durable admission.

Accepted derived retrieval uses FTS5 lexical retrieval plus Qwen dense retrieval/reranking only over already-eligible canonical records. Retrieval cannot establish, modify, resurrect, or forget truth.

The owner-authorized provider-assisted `recall_memory` path remains bounded and explicit. It exposes only eligible cloud-safe facets, reconstructs canonical data inside JARVIS, performs deterministic grounding checks, and abstains on ambiguity/provider failure.

The original strict independent semantic release verifier and automatic Phase-4.5E conversational semantic-memory injection remain deferred.

---

## Step 5 — accepted bounded provider resilience

The accepted Step-5 scope does **not** implement a local conversational brain. It adds a deterministic failure boundary around the realtime-provider session.

```text
LiveKit realtime terminal error
        |
        v
JARVIS classify_provider_failure()
        |
        +-> quota/rate/auth/permission/model/server
        +-> timeout/connection/unknown
        |
        v
ProviderResilienceState = DEGRADED
        |
        v
WindowsLocalStatusSpeech
        |
        v
existing selected JARVIS output
        |
        v
explicit failed session close
        |
        v
outer lifecycle returns toward wake/idle
```

Accepted properties:

- terminal failure classification is bounded deterministic JARVIS code;
- local truthful status speech does not depend on the failed cloud TTS path;
- no second cloud provider is silently selected;
- no local LLM/STT/conversational TTS stack is claimed;
- later healthy provider state marks recovery.

Acceptance evidence: `docs/research/STEP_5_MINIMAL_PROVIDER_RESILIENCE_ACCEPTANCE.md`.

---

## Step 6 — accepted bounded source-aware research

```text
latest canonical USER request
        |
        v
active conversational brain
        |
        | decides current research is warranted
        v
search_web
        |
        v
CurrentResearchService
        |
        v
replaceable retrieval adapter
accepted first adapter: Exa
        |
        v
normalized source evidence
URL/title/domain/excerpt/timestamp
        |
        v
JARVIS truth/source sufficiency policy
        |
        v
active brain synthesizes answer
```

Accepted properties:

- retrieval is independent of the active conversational-brain provider;
- JARVIS owns research warrant, provenance normalization, truth/research status, source sufficiency, and fail-closed behavior;
- stable knowledge questions can be blocked from unnecessary network retrieval;
- explicit/current/fact-check/authoritative requests may require stronger live evidence;
- web evidence gains no memory/identity/authority/file/device power;
- search/provider failure is reported as unavailable rather than silently described as freshly verified.

Acceptance evidence: `docs/research/STEP_6_KNOWLEDGE_TRUTHFULNESS_ACCEPTANCE.md`.

---

## Step 7 — accepted governed capability runtime + safe reads

Step 7 establishes the first shared execution contract without turning JARVIS into a giant universal agent framework.

### End-state routing principle

```text
User goal
   |
   v
JARVIS brain
   |
   v
Capability Resolver
   |
   v
canonical AuthorityService
   |
   v
best mature bounded execution substrate
   |
   +-> semantic/native capability when available
   +-> structured specialist automation when assigned to that roadmap step
   +-> visual computer use as later fallback
   |
   v
verification / structured result / audit
```

Operational rule:

**JARVIS decides WHAT. AuthorityService decides WHETHER. Mature execution technology decides HOW.**

Step 7 activates only the read subset of this architecture.

### Capability discovery

`CapabilityResolver` merges deterministic built-in capabilities with dynamic discovery sources.

Accepted discovery sources:

- `WinAppCliSchemaSource` executes only Microsoft `winapp --cli-schema` with `shell=False`, bounded timeout, JSON parsing, and imports only the UI schema family;
- `WindowsOdrSource` executes only `odr list` when available, parses registered server metadata, never launches a server or MCP tool, and truthfully reports `UNAVAILABLE` when ODR is absent.

Discovered metadata is explicitly untrusted/non-authoritative.

Duplicate source IDs or duplicate capability identities fail closed.

Unexpected programming errors are not hidden as normal discovery degradation.

On the accepted owner machine:

- `windows.winapp` was `AVAILABLE`;
- `windows.odr` was `UNAVAILABLE` and did not block the catalog;
- `windows.winapp:desktop.ui` surfaced semantic UI operations but remained `execution_enabled=false`.

### Generic execution contract

```text
CapabilityRequest
       |
       v
resolve one enabled capability
       |
       v
executor.prepare()
 -> bounded validated parameters
 -> semantic target/effect summary
 -> ActionAttributes
       |
       v
CapabilityAuthorityBroker
 -> canonical ActionProposal
 -> canonical AuthorityService
 -> Windows Hello/T3 for private reads
 -> one-time permit
       |
       v
revalidate_and_consume()
       |
       v
executor.execute()
       |
       v
CapabilityResult
 -> status/data/reason
 -> elapsed/truncated/provenance
       |
       v
privacy-aware audit
```

Only executable Step-7 descriptors are registered with execution adapters. Discovery-only surfaces cannot execute merely because they appear in the catalog.

### Accepted executable operations

Local system read capability:

- `system_status`
- `list_processes`

Local project/file read capability:

- `file_info`
- `list_directory`
- `list_project_files`
- `search_project`
- `read_file`
- `read_document`

### Routine system metadata

`system_status` uses bounded local `psutil`, `platform`, and datetime evidence for CPU/RAM/disk/uptime/machine/timezone status.

This routine machine metadata uses the bounded T0 authority path.

Process-list inspection is treated as private local read rather than routine metadata.

### Approved-root local reads

Local project/file reads operate only beneath configured approved root aliases.

Accepted protection rules:

- root/path values are normalized and validated;
- absolute paths and parent traversal are rejected where not explicitly part of the approved-root contract;
- resolved paths must remain beneath the resolved approved root;
- symlink/junction escapes are rejected by resolved containment;
- `.git`/hidden and credential-like sensitive paths are excluded from normal project discovery/read surfaces;
- file/document sizes and result counts are bounded;
- direct text reads reject binary content;
- secret-like released content is blocked/redacted according to the read surface;
- Git is preferred for project inventory when present;
- ripgrep is preferred for text search when present, with a bounded Python fallback.

### Isolated document reader

Supported document conversion types:

- PDF
- DOCX
- PPTX
- XLS
- XLSX

Microsoft MarkItDown `0.1.7` is retained as the accepted mature document-conversion technology, but it is **not** installed in the main JARVIS environment.

Owner testing exposed a Windows dependency conflict: MarkItDown/Magika selected ONNX Runtime `1.20.1`, while the accepted JARVIS vision stack requires ONNX Runtime `1.29.0`.

The accepted architecture therefore uses a disposable sidecar virtual environment:

```text
main JARVIS venv
 -> ONNX Runtime 1.29.0
 -> vision/wake/inference stack unchanged

isolated MarkItDown sidecar
 -> MarkItDown 0.1.7
 -> NumPy 2.4.6 on accepted owner machine
 -> ONNX Runtime 1.20.1 on accepted owner machine
```

`jarvis-setup-document-reader` recreates the sidecar cleanly and provisions it with Python isolated mode plus pip isolated mode.

The sidecar strips inherited Python/pip environment state and common secret-bearing environment variables, executes with `shell=False`, bounded timeout, bounded JSON output, and validates MarkItDown/NumPy/ONNX/converter imports before reporting ready.

Converted content is still treated as untrusted local data and passes JARVIS release/secret checks after conversion.

### Voice-facing local-read tool

Production voice exposes one generic `inspect_local` function-tool rather than one model tool per user task.

Before any local read, the tool checks the latest accepted canonical USER turn for a bounded local-read warrant. If the current turn does not explicitly support local machine/project inspection, the tool returns/raises a grounding refusal rather than executing.

This guard was exercised during owner acceptance when unrelated meeting audio caused an attempted local inspection; JARVIS rejected it with `user turn does not explicitly authorize inspect`.

Private local/project operations then pass through canonical authority and may trigger exact-action Windows Hello verification.

Returned local data is explicitly marked untrusted and must not be followed as instructions.

### Step-7 explicit non-capabilities

Step 7 intentionally does **not** enable:

- file/document writes;
- arbitrary shell or PowerShell;
- desktop/application/device control;
- browser execution;
- installation or deletion;
- coding/project mutation;
- external communication;
- calendar/email actions;
- ODR/MCP server tool invocation;
- Windows App Actions execution;
- Playwright browser control;
- plugin/skill lifecycle extensibility.

Those remain later roadmap steps.

### Owner acceptance

Owner acceptance on 2026-09-09 proved:

- dynamic discovery;
- real routine system telemetry;
- positive private project read through Windows Hello + canonical authority;
- explicit Windows Hello cancellation failed closed with zero private content returned;
- one transient Windows Hello helper timeout also failed closed before execution;
- immediate retry succeeded;
- real XLSX content was extracted by the isolated MarkItDown sidecar with expected marker/provenance;
- production voice used `system_status` and `read_file` successfully;
- ambiguous meeting speech did not gain local-inspection authority.

Acceptance evidence: `docs/research/STEP_7_GOVERNED_CAPABILITY_RUNTIME_ACCEPTANCE.md`.

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
- candidate extraction controlled separately by its explicit configuration;
- bounded provider-assisted semantic recall enabled only when configured;
- Step-7 OPA binary and Windows Hello helper supplied through the accepted authority configuration;
- MarkItDown document conversion provisioned separately with `jarvis-setup-document-reader`.

API keys remain outside normal machine-profile state. Startup preflight checks only the credential required by the selected active provider.

Fail-closed hardware behavior remains accepted: if the configured Pocket3 device is absent, startup does not silently choose a random microphone.

The bounded Step-5 closure still does not allow normal conversational startup without valid active-provider credentials because no full local conversational intelligence stack has been accepted.

---

## Known accepted residuals through Step 7

The following are intentionally **not** claimed as solved:

- T2 `CORROBORATED_OWNER` production promotion;
- CAM++ owner-speaker threshold promotion;
- LR-ASD active-speaker admission threshold promotion;
- ambient meeting/other-speaker false USER-turn elimination;
- replay/deepfake-complete biometric defense;
- automatic Phase-4.5E semantic memory injection;
- strict independent semantic recall verifier;
- full local/offline conversation;
- automatic cloud-provider failover;
- browser/app/device/file-write/coding authority;
- Windows ODR availability on the accepted owner OS;
- generic MCP/App Actions/Playwright execution;
- proactive/background automation;
- plugin/skill lifecycle;
- self-modification/self-repair authority.

These remain assigned to later roadmap work or previously documented bounded deferrals. They must not be inferred from the existence of the Step-7 capability runtime.

---

## Next architecture work

After Step 7 merges to protected `main`, Step 8 — Notes, Tasks, Reminders, and Scheduling — must begin research-first.

Step 8 must reuse canonical conversation truth, durable memory boundaries, `AuthorityService`, and the Step-7 capability/runtime patterns rather than building a parallel task/reminder brain or permission system.
