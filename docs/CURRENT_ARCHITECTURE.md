# JARVIS V1 Current Architecture

## Status

**STEP 3 CORE ARCHITECTURE IS ACCEPTED ON THE FINALIZATION BRANCH. BOUNDED T2 IS ACTIVE IN PRODUCTION. SPOKEN ACTOR BINDING IS DEFERRED, SO NORMAL T2 KEEPS `actor_unambiguous=false`. PR #18 IS NOT YET MERGED TO `main`.**

This file describes architecture that actually exists and is accepted. Active work order belongs in `docs/CURRENT_PLAN.md`; experiments/evidence belong in `docs/research/`; durable decisions belong in `docs/decisions/`.

---

## Accepted top-level architecture

```text
                               JARVIS V1
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
        VOICE                    VISION                  AUTHORITY
          │                        │                        │
Pocket3 microphone          Pocket3 video            typed context/evidence
          │                        │                        │
LiveKit MediaDevices        OpenCV camera            T0-T3 trust
AEC + NS + HPF + AGC             │                        │
          │                 RF-DETR + OC-SORT          ActionProposal
canonical user PCM               │                        │
          │                 head/face association      R0-R5 risk floor
          │                        │                        │
          │                 YuNet + SFace              fail-closed OPA
          │                        +                        │
          │                 MiniFAS liveness           approvals
          │                        │                        │
          │                 bounded OWNER T2      Windows Hello / T3
          │                        │                        │
          ├── CAM++ speaker shadow ─────┐                 │
          ├── LR-ASD active-speaker ────┼── diagnostics ──┤
          └── Sortformer overlap ───────┘                 │
                                                           │
                                      final revalidation + one-time permit
```

Permanent rule: **identity/perception/model evidence is not execution permission.**

---

## Machine configuration and startup

Normal startup is machine-profile driven:

```text
%LOCALAPPDATA%\JARVIS\machine.json
        +
Windows environment for provider secrets
        ↓
startup preflight
        ↓
jarvis-voice / jarvis-dev
```

Accepted target-machine roles:

- Pocket3 microphone selected by stable Windows WASAPI `name + hostapi` identity;
- conversation output through NVIDIA `24'TV` at 48 kHz;
- local wake model persisted;
- realtime provider boundary retained;
- LR-ASD/CAM++/Sortformer assets locally managed;
- Vision, speaker, and active-speaker switches persisted;
- API keys remain outside normal machine-profile state.

Decision: `docs/decisions/ADR-012_MACHINE_CONFIGURATION_AND_STARTUP_PREFLIGHT.md`.

---

## Conversation audio — one production microphone owner

```text
Pocket3 microphone @ 48 kHz mono
        ↓
LiveKit rtc.MediaDevices.open_input()
WebRTC AEC + NS + HPF + AGC
        ↓
canonical processed user PCM
        ├── wake / realtime conversation
        ├── CAM++ speaker shadow
        ├── LR-ASD active-speaker shadow
        └── native Sortformer overlap shadow
        ↓
LiveKit MediaDevices output / APM render reference
        ↓
NVIDIA HDMI @ 48 kHz → 24'TV
```

Requirements:

- LiveKit MediaDevices is the only production Pocket3 microphone owner;
- capture and render share the WebRTC APM/AEC reference;
- identity diagnostics reuse canonical PCM;
- diagnostics never open a second production microphone.

Rejected production architecture: independent simultaneous LiveKit + GStreamer ownership of the Pocket3 microphone.

Decisions:

- `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`
- `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`

---

## Vision and bounded OWNER T2

```text
Pocket3 video
        ↓
OpenCVCameraSource + monotonic CapturedFrame
        ↓
RF-DETR person detection
        ↓
OC-SORT persistent track
        ↓
head association
        ↓
YuNet + SFace temporal OWNER identity
        +
MiniFAS temporal passive liveness
        ↓
same visual track + fresh evidence
        +
current active/unlocked matching Windows WTS session
        ↓
T2 CORROBORATED_OWNER
```

T2 is short-lived contextual OWNER trust. The production bridge requires:

1. temporal enrolled OWNER SFace state `OWNER_CANDIDATE`;
2. passive liveness `LIVE` on the same visual track;
3. fresh fused evidence (2-second runtime TTL);
4. matching Windows WTS session; and
5. active/unlocked Windows session.

Any stale evidence, identity ambiguity, unknown subject, spoof/uncertain liveness, WTS mismatch, Windows lock, or WTS failure drops the context to `UNVERIFIED`.

Normal T2 currently emits:

```text
trust_tier = CORROBORATED_OWNER
actor_unambiguous = false
attention_state = UNAVAILABLE
```

The production smoke on 2026-09-04 confirmed that normal JARVIS can identify the visible user as OWNER and report Tier 2 without falsely claiming T3.

Decision: `docs/decisions/ADR-015_BOUNDED_T2_OWNER_CONTEXT.md`.

---

## Encrypted OWNER profile

The accepted local encrypted OWNER profile contains FACE + VOICE modalities.

Properties:

- one OWNER profile;
- AES-256-GCM protected payloads;
- DPAPI-sealed per-profile key material;
- explicit Windows-Hello-gated profile mutations;
- face templates are multi-prototype SFace data;
- voice templates are CAM++ prototypes;
- raw enrollment audio/video is not retained by default;
- normal conversation cannot auto-enroll or silently adapt OWNER templates.

---

## Audio-first CAM++ speaker shadow

```text
canonical LiveKit user PCM
        ↓
local speech-region + quality gate
        ↓
CAM++ embedding
        ↓
encrypted OWNER voice prototype comparison
        ↓
diagnostic similarity
```

Accepted behavior:

- asynchronous and non-blocking to conversation;
- short/poor/missed speech becomes `INSUFFICIENT`;
- no production OWNER-speaker threshold is promoted;
- no CAM++ result directly changes authority.

CAM++ remains reusable evidence for future spoken actor binding.

Decision: `docs/decisions/ADR-014_AUDIO_FIRST_SPEAKER_SHADOW.md`.

---

## LR-ASD active-speaker shadow

```text
canonical LiveKit user PCM ───────────────┐
                                           ├── monotonic overlap → LR-ASD
Vision OWNER track/head timeline ─────────┘
```

Accepted evidence demonstrates useful positive OWNER-speaking and strong negative phone/off-camera/replayed-speech behavior, but short-window genuine-OWNER recall is variable. Canonical 0 ms alignment is retained; no fixed AV correction and no production LR-ASD threshold are promoted.

LR-ASD remains corroborative/negative evidence for future actor binding, not a T2 or authority gate by itself.

Do not reopen basic replay/alignment calibration unless a new production failure or model/runtime change creates a new question.

---

## Native Sortformer overlap shadow

The production runtime also reuses canonical PCM for native NeMo-Speech Sortformer overlap/speaker-change evidence on the RTX 5060 Ti.

Purpose:

- identify multi-speaker/overlap ambiguity;
- provide speaker-change evidence for future turn-specific actor binding;
- remain asynchronous and non-authoritative.

The production T2 smoke successfully loaded the native CUDA runtime and produced `single_speaker` evidence during normal OWNER turns.

Sortformer does not own another microphone and does not directly grant authority.

---

## Authority architecture

```text
identity/context evidence
        ↓
InteractionContext / graduated trust
        ↓
immutable ActionProposal
        ↓
deterministic R0-R5 risk floor
        ↓
fail-closed OPA policy
        ↓
proposal-bound approval / strong verification
        ↓
final revalidation
        ↓
one-time execution permit
        ↓
execution result + privacy-aware audit
```

Accepted trust vocabulary:

- T0 `UNVERIFIED`
- T1 `PRESENT_CONTEXT`
- T2 `CORROBORATED_OWNER`
- T3 `VERIFIED_OWNER`

Accepted current risk boundary:

```text
R0 ROUTINE                  -> T0
R1 PRIVATE_READ             -> T2 + policy/direct-intent rules
R2 REVERSIBLE_LOCAL_CHANGE  -> T2 + policy/direct-intent rules
R3 PERSISTENT_OR_EXTERNAL   -> T2 + approval + actor_unambiguous
R4 CRITICAL                 -> T3 + strong verification
R5 RESTRICTED_DEV_ONLY      -> T3 + strong verification + extra context
```

Because current T2 deliberately keeps `actor_unambiguous=false`, spoken R3 persistent/external actions remain fail-closed until spoken actor binding is explicitly resumed and accepted.

Critical R4 authority remains T3 / Windows Hello strong verification.

Permanent invariants:

```text
face match       ≠ permission
speaker match    ≠ permission
liveness         ≠ permission
active speaker   ≠ permission
overlap model    ≠ permission
wake word        ≠ owner
Windows unlocked ≠ owner speaking
LLM confidence   ≠ permission
```

Decisions:

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-015_BOUNDED_T2_OWNER_CONTEXT.md`
- `docs/decisions/ADR-016_DEFER_SPOKEN_ACTOR_BINDING_AND_RESUME_ROADMAP.md`

---

## Privacy and observability boundary

- raw biometric audio/video is memory-only by default;
- bounded encrypted biometric templates exist only through explicit enrollment;
- secrets/tokens are not normal logs or model context;
- audit records authority/state transitions without becoming hidden surveillance;
- diagnostic model outputs cannot silently change authority;
- failures and insufficient evidence remain explicit.

---

## Deferred identity hardening

Not current Step-4 blockers:

- turn-specific spoken actor binding;
- non-OWNER CAM++ calibration required for that binding;
- additional replay/synthetic/cloned-voice defenses if research proves useful;
- short-turn actor continuity if practical use needs it;
- stronger overlap/diarization semantics beyond current Sortformer evidence;
- lip reading / AV target-speaker extraction;
- fixed-camera attention/gaze.

These remain a bounded future hardening package. They must plug into the existing `InteractionContext.actor_unambiguous` / authority path rather than create a parallel authorization system.

---

## Step 4 architecture state

**No Step-4 memory/storage architecture is accepted yet.**

Step 4 must begin research-first and define one authoritative context/memory owner with clear boundaries among:

- live/session working context;
- durable semantic memory;
- episodic memory;
- reflection/memory candidates;
- provenance/confidence/supersession/forgetting;
- retrieval/ranking;
- transient emotional interaction state.

Models may propose memory candidates but may not directly mutate canonical durable memory. Provider/storage/retrieval boundaries must remain replaceable.
