# JARVIS V1 Current Architecture

## Status

**STEP 3 ACCEPTED FOR CLOSURE. IDENTITY / TRUST / AUTHORITY / OBSERVABILITY FOUNDATION IS IMPLEMENTED. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 REMAINS DISABLED. STEP 4 MEMORY/CONTEXT RESEARCH IS NEXT AFTER PROTECTED-MAIN MERGE.**

This file describes only architecture that actually exists and is accepted. Detailed experiments/evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable decisions belong in `docs/decisions/`.

---

## Top-level accepted architecture

```text
                               JARVIS V1
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
        VOICE                    VISION                  AUTHORITY
          │                        │                        │
Pocket3 microphone          Pocket3 video            typed evidence
          │                        │                        │
LiveKit MediaDevices        OpenCV camera            deterministic trust
AEC + NS + HPF + AGC             │                        │
          │                 RF-DETR + OC-SORT          proposal/risk/policy
          │                        │                        │
Gemini/OpenAI               head/face/liveness       approvals / Windows Hello
          │                        │                        │
NVIDIA 48 kHz → TV          OWNER context                 │
          │                        │                        │
          ├──── CAM++ speaker shadow ─────┐                │
          │                               │                │
          └──── LR-ASD active-speaker ────┴── evidence ───┤
                                                          │
                                      no sensor/model grants permission
```

Permanent rule: **identity/perception evidence is not execution permission.**

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
jarvis-voice
```

Accepted current-machine roles:

- Pocket3 microphone: stable Windows WASAPI `name + hostapi` selector;
- conversation output: NVIDIA `24'TV`, Windows WASAPI, 48 kHz;
- wake model: persisted local path;
- provider: Gemini on the current machine, with provider boundary retained;
- LR-ASD AVA checkpoint: managed/integrity-verified local asset;
- CAM++ speaker model: managed/integrity-verified local asset;
- vision/speaker/active-speaker feature switches: persisted.

Machine profile values outrank stale non-secret ambient `JARVIS_*` overrides unless explicit diagnostic override mode is enabled. API keys remain environment-only.

Decision: `docs/decisions/ADR-012_MACHINE_CONFIGURATION_AND_STARTUP_PREFLIGHT.md`.

---

## Conversation audio — one production microphone owner

Accepted production path:

```text
Pocket3 microphone @ 48 kHz mono
        ↓
LiveKit rtc.MediaDevices.open_input()
WebRTC AEC + NS + HPF + AGC
        ↓
canonical processed user PCM
        ├── wake / AgentSession / realtime conversation
        ├── CAM++ speaker shadow
        └── LR-ASD audio input
        ↓
LiveKit MediaDevices output / APM render reference
        ↓
NVIDIA HDMI @ 48 kHz
        ↓
24'TV speakers
```

Requirements:

- LiveKit MediaDevices is the only production Pocket3 microphone owner;
- capture and render share one WebRTC APM/AEC reference;
- Bluetooth/Tribit 44.1-kHz A2DP is not the accepted production render path;
- JARVIS playback should not become a normal user turn;
- real human barge-in remains handled by the realtime conversation stack;
- speaker/active-speaker diagnostics consume the canonical PCM and never open a second production microphone path.

Rejected architecture:

```text
Pocket3 mic
   ├── LiveKit/PortAudio
   └── independent GStreamer wasapi2src
```

Real hardware showed that dual independent ownership is not reliable on this machine. Historical GStreamer paired-A/V diagnostic code may remain for engineering evidence/explicit diagnostics, but it is not the `jarvis-voice` production path.

Decisions:

- `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`
- `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`

---

## Vision / OWNER evidence

Accepted Vision pipeline:

```text
Pocket3 video
        ↓
OpenCVCameraSource
monotonic CapturedFrame
        ↓
RF-DETR person detection
        ↓
OC-SORT persistent track
        ↓
head association
        ↓
YuNet + SFace OWNER identity
        +
MiniFAS temporal passive liveness
        +
active-liveness fallback when required
        ↓
same Windows session + same visual track
        ↓
OWNER-context evidence
```

OWNER visual evidence is bound to session/track/freshness and remains evidence rather than permission.

The integrated Vision preview displays the same canonical runtime state; it is an observability surface, not a second camera/perception owner.

Attention/gaze remains deferred because the movable Pocket3 is not a stable monitor-relative gaze sensor.

---

## Encrypted OWNER profile

JARVIS maintains a local encrypted OWNER profile. Current accepted modalities are:

```text
face + voice
```

Voice enrollment is explicit and Windows-Hello-gated. Raw enrollment audio is memory-only and discarded. Normal conversation cannot auto-enroll or adapt OWNER voice prototypes from similarity alone.

---

## Audio-first CAM++ speaker shadow

Accepted speaker path:

```text
canonical LiveKit processed user PCM
        ↓
ObservedSessionAudioInput
        ↓
bounded in-memory turn capture
        ↓
local Silero speech-region gate
        ↓
quality gate
        ↓
CAM++ embedding
        ↓
encrypted OWNER prototype comparison
        ↓
diagnostic similarity only
```

Real-machine enrollment accepted:

- 12 accepted natural speech samples;
- 6 persisted prototypes;
- embedding dimension 192;
- enrollment coverage min `0.7593`, p05 `0.7749`, median `0.8726`.

First ordinary-conversation accepted OWNER similarities were `0.6737–0.7450`. CAM++ inference was observed at `57.5–173.2 ms` and ran asynchronously off the conversation critical path.

Current disposition:

- no production OWNER threshold selected;
- no speaker classification promoted to authority;
- poor/short/missed speech becomes `INSUFFICIENT`, not “not OWNER”;
- speaker shadow can operate without Vision;
- missing enrollment/model/dependency disables the diagnostic observer rather than normal conversation.

Decision: `docs/decisions/ADR-014_AUDIO_FIRST_SPEAKER_SHADOW.md`.

---

## LR-ASD active-speaker shadow

Accepted integration:

```text
canonical LiveKit user PCM ───────────────┐
                                           ├── monotonic overlap → LR-ASD
normal Vision OWNER track/head timeline ──┘
```

The provider scores only when speech quality, fresh same-track OWNER context, timestamps, and sufficient visual continuity are available. Missing evidence fails closed.

Accepted controlled evidence includes:

- OWNER speech: strong positive;
- TV/off-camera speech: strong negative;
- OWNER voice replay while OWNER is visually silent: strong negative for LR-ASD;
- temporary head loss: insufficient;
- OWNER + concurrent background/other speech: high LR-ASD score because OWNER really is speaking.

The last case is a known semantic boundary: LR-ASD does not prove OWNER is the only speaker in mixed audio. Therefore active-speaker confirmation remains disabled and future overlap/diarization work is required before stronger audio/AV authority can be considered.

No LR-ASD deployment threshold is selected.

Evidence:

- `docs/research/STEP_3B11_SINGLE_OWNER_ACTIVE_SPEAKER_ACCEPTANCE_RESULTS.md`
- `docs/research/STEP_3B11_LR_ASD_BAKEOFF_HARNESS.md`
- `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`

---

## Authority architecture

Accepted deterministic authority flow:

```text
identity/context evidence
        ↓
graduated trust
        ↓
immutable ActionProposal
        ↓
deterministic risk floor
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

**T2 remains disabled.** The current strong-verification path for consequential authority is Windows Hello.

Permanent invariants:

```text
face match       ≠ permission
speaker match    ≠ permission
liveness         ≠ permission
active speaker   ≠ permission
attention        ≠ permission
wake word        ≠ owner
Windows unlocked ≠ owner speaking
LLM confidence   ≠ permission
```

Decision: `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`.

---

## Privacy / observability boundary

- raw biometric audio/video is memory-only by default;
- encrypted bounded biometric templates exist only for explicit accepted enrollment;
- secrets/tokens are not normal logs/model context;
- audit records operational state/authority decisions rather than becoming surveillance;
- diagnostic model outputs cannot silently change authority;
- failures/insufficient evidence remain explicit.

---

## Step-3 deferred identity work

The following are deliberately **not current architecture** and do not block Step-3 completion:

- streaming overlap/speaker-change detection;
- replay/synthetic/cloned-voice countermeasures;
- direct non-owner CAM++ calibration and any speaker threshold;
- real second-person E/F LR-ASD calibration;
- short-turn speaker continuity;
- lip reading / AV target-speaker extraction;
- fixed-camera attention/gaze;
- any T2 composition or biometric authority promotion.

They may be revisited when a later product capability demonstrates a concrete requirement.

---

## Next architecture work

After the Step-3 closure PR merges, **Step 4 — Live Context and Personal Memory** is active.

Step 4 must introduce exactly one authoritative JARVIS context/memory owner, keep session context separate from durable memory, preserve provenance/correction/forgetting, prevent models from directly writing durable memory, and keep storage/retrieval providers replaceable.

No Step-4 storage/provider architecture is selected yet; research comes first.
