# JARVIS V1 Current Architecture

## Status

**STEP 3 COMPLETE + MERGED. IDENTITY / TRUST / AUTHORITY / OBSERVABILITY FOUNDATION IS ACCEPTED ON `main`. CAM++ AND LR-ASD REMAIN SHADOW EVIDENCE ONLY; T2 REMAINS DISABLED. STEP 4 MEMORY/CONTEXT ARCHITECTURE IS NOT YET SELECTED.**

This file describes only architecture that actually exists and is accepted. Detailed experiments/evidence belong in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; durable decisions belong in `docs/decisions/`.

---

## Accepted top-level architecture

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
realtime provider           head/face/liveness       approvals / Windows Hello
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

- Pocket3 microphone selected by stable Windows WASAPI `name + hostapi` identity;
- conversation output through NVIDIA `24'TV` at 48 kHz;
- local wake model path persisted;
- realtime provider boundary retained;
- LR-ASD and CAM++ model assets locally managed/integrity checked;
- vision/speaker/active-speaker switches persisted.

API keys remain outside normal machine-profile state.

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
        ├── wake / AgentSession / realtime conversation
        ├── CAM++ speaker shadow
        └── LR-ASD audio input
        ↓
LiveKit MediaDevices output / APM render reference
        ↓
NVIDIA HDMI @ 48 kHz → 24'TV
```

Requirements:

- LiveKit MediaDevices is the only production Pocket3 microphone owner;
- capture and render share the WebRTC APM/AEC reference;
- speaker/active-speaker diagnostics reuse canonical PCM;
- diagnostics do not open a second production microphone;
- Bluetooth/Tribit is not the accepted production render path.

Rejected production architecture:

```text
Pocket3 mic
   ├── LiveKit/PortAudio
   └── independent GStreamer wasapi2src
```

Historical paired-GStreamer diagnostic code may remain as engineering evidence, but it is not the `jarvis-voice` production path.

Decisions:

- `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`
- `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`

---

## Vision / OWNER evidence

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

OWNER visual evidence is freshness/session/track bound and remains evidence rather than permission.

Attention/gaze remains deferred because the movable Pocket3 is not a stable monitor-relative gaze sensor.

---

## Encrypted OWNER profile

The accepted local encrypted OWNER profile currently contains:

```text
face + voice
```

Voice enrollment is explicit and Windows-Hello-gated. Raw enrollment audio is memory-only and discarded. Normal conversation cannot auto-enroll or adapt OWNER voice prototypes from similarity alone.

---

## Audio-first CAM++ speaker shadow

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

Real-machine acceptance:

- 12 accepted enrollment samples;
- 6 persisted prototypes;
- 192-dimensional embeddings;
- enrollment coverage min `0.7593`, p05 `0.7749`, median `0.8726`;
- ordinary-conversation OWNER similarities observed at `0.6737–0.7450`;
- observed inference `57.5–173.2 ms` and non-blocking to conversation.

Current disposition:

- no production OWNER speaker threshold selected;
- no speaker classification promoted to authority;
- poor/short/missed speech becomes `INSUFFICIENT`;
- speaker shadow may operate without Vision;
- missing enrollment/model/dependency disables the diagnostic observer rather than normal conversation.

Decision: `docs/decisions/ADR-014_AUDIO_FIRST_SPEAKER_SHADOW.md`.

---

## LR-ASD active-speaker shadow

```text
canonical LiveKit user PCM ───────────────┐
                                           ├── monotonic overlap → LR-ASD
normal Vision OWNER track/head timeline ──┘
```

The provider scores only when speech quality, fresh same-track OWNER context, timestamps, and sufficient visual continuity are available.

Accepted evidence includes:

- OWNER speech → strong positive;
- TV/off-camera speech → strong negative;
- replayed OWNER voice while OWNER visually silent → strong negative for LR-ASD;
- temporary head loss → insufficient;
- OWNER + concurrent other/background speech → high LR-ASD because OWNER really is speaking.

That last case is a known semantic boundary: LR-ASD does not prove OWNER is the only speaker in mixed audio. No active-speaker deployment threshold is selected and `active_speaker_confirmed` remains false.

Evidence:

- `docs/research/STEP_3B11_SINGLE_OWNER_ACTIVE_SPEAKER_ACCEPTANCE_RESULTS.md`
- `docs/research/STEP_3B11_LR_ASD_BAKEOFF_HARNESS.md`
- `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`

---

## Authority architecture

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

**T2 remains disabled.** Windows Hello remains the accepted strong-verification path for consequential authority.

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
- bounded encrypted biometric templates exist only through explicit enrollment;
- secrets/tokens are not normal logs/model context;
- audit records state transitions/authority decisions without becoming surveillance;
- diagnostic model outputs cannot silently change authority;
- failures and insufficient evidence remain explicit.

---

## Deferred identity work

Not current architecture and not Step-4 blockers:

- streaming overlap/speaker-change detection;
- replay/synthetic/cloned-voice countermeasures;
- direct non-owner speaker calibration/thresholds;
- E/F real-second-person LR-ASD calibration;
- short-turn speaker continuity;
- lip reading / AV target-speaker extraction;
- fixed-camera attention/gaze;
- any T2 composition or biometric authority promotion.

Tracked in Issue #14.

---

## Step 4 architecture state

**No Step-4 storage/memory framework is selected yet.**

Research must first define one authoritative JARVIS context/memory owner and establish boundaries among:

- live/session working context;
- durable semantic memory;
- episodic memory;
- reflection/memory candidates;
- provenance/confidence/supersession/forgetting;
- retrieval/ranking;
- transient emotional interaction state.

Models may propose memory candidates but may not directly mutate durable canonical memory. Provider/storage/retrieval boundaries must remain replaceable.
