# ADR-009 — Step 3 Sensor Fabric and Paired A/V Boundary

Status: **ACCEPTED FOR IMPLEMENTATION AS A BOUNDED 3B.11 PREREQUISITE**

Date: 2026-08-31

## Context

Step 3B.11 live active-speaker testing exposed a foundation problem rather than a model-threshold problem: JARVIS currently treats the camera and canonical conversation microphone as largely independent runtime resources. That works for normal conversation and vision, but it is not a safe permanent basis for audio-visual evidence when JARVIS may use multiple cameras with their own microphones.

The permanent product direction includes at least a fixed webcam and the DJI Pocket 3, with future sensors possible. Audio-visual inference such as active-speaker detection must not silently combine video from one physical source with unrelated audio from another source.

This ADR does **not** create a new milestone. It is the minimum architecture correction required inside Phase 3B.11 before active-speaker acceptance can continue.

## Decision

JARVIS will introduce a provider-neutral Sensor Fabric boundary.

A physical sensor source exposes identity, capabilities, health, and its media endpoints. An audio-video source additionally owns the relationship between its video and paired audio streams.

Conceptual contract:

```text
AVSource
├── source identity
├── capabilities
├── video endpoint
├── paired audio endpoint
├── timestamp/synchronization state
└── health
```

### Paired-source invariant

Any inference whose meaning depends on audio/video correspondence must use audio and video from the same accepted AV source unless an explicit separately calibrated synchronization relationship exists.

Examples:

```text
Pocket3 video + Pocket3/Mic-Mini audio → allowed
Lenovo video + Lenovo microphone       → allowed
Lenovo video + Pocket3 microphone      → not allowed by default
```

### Interaction vs observation

Changing which camera is used for inspection does not automatically change the conversation microphone.

JARVIS may keep one interaction source while using another source for visual inspection. Audio-visual evidence remains source-bound.

### Source-switch invalidation

Source-bound temporal evidence must not be stitched across an AV-source transition. A source change requires fresh source-bound evidence where applicable.

### Echo/output invariant

JARVIS speaker output is not user speech. The exact render signal must remain available to the audio-processing boundary as echo reference. Residual playback must not be promoted into user activity, speaker identity, or active-speaker evidence.

### Authority invariant

Sensor selection, synchronization, active-speaker output, face, liveness, speaker identity, attention, gesture, and model confidence remain evidence only. None directly grants consequential action authority.

## Implementation strategy

Migration is parallel and fail-safe:

```text
current accepted runtime remains primary
        +
new Sensor Fabric introduced passively
        ↓
automated validation
        ↓
shadow / real-machine validation
        ↓
explicit human acceptance
        ↓
only then promote a replacement path
```

The current camera/audio implementation must not be removed before its replacement is accepted.

## Minimum implementation scope for 3B.11

Only the following is required before returning to active-speaker acceptance:

1. provider-neutral source/capability/sync-health contracts;
2. source identity that can later map physical Windows video/audio endpoints;
3. a Pocket-3 adapter that can preserve the current accepted runtime while exposing paired-source metadata;
4. timestamp/synchronization diagnostics sufficient to determine whether an active-speaker window is usable;
5. render-reference/AEC integration sufficient to prevent JARVIS playback from becoming false user activity on the selected interaction microphone;
6. active-speaker provider input changed from a global microphone assumption to an exact source-bound A/V window.

The following are explicitly **not required to finish 3B.11**:

- full autonomous sensor orchestration;
- pointing/reference grounding;
- gaze/attention implementation;
- Lenovo-specific runtime integration before the hardware is present;
- depth/smart-glasses integration;
- a general scene/world-model rewrite.

Those capabilities can use the Sensor Fabric later without blocking the current Step-3 goal.

## Technology direction

Mature components are preferred over custom implementations:

- Windows physical-device identity/ContainerID where reliable;
- GStreamer as the leading candidate for clocked Windows A/V capture when the current capture boundary is replaced;
- WebRTC Audio Processing Module/AEC as the primary echo-cancellation provider;
- NVIDIA Maxine AEC as a bounded challenger only if needed;
- LR-ASD and NVIDIA Maxine Active Speaker Detection behind a JARVIS-owned provider boundary;
- provider/client-owned realtime activity signaling where supported, rather than allowing acoustic echo to control model turn-taking.

Technology selection remains subject to real-machine acceptance.

## Consequences

Positive:

- current JARVIS remains intact during migration;
- active-speaker evidence gains an explicit synchronization boundary;
- future Lenovo/Pocket3 switching does not require another architecture rewrite;
- mature capture/AEC/ASD providers remain replaceable;
- failed new providers can be rolled back without deleting known-good runtime paths.

Cost:

- one small architecture layer is introduced before 3B.11 can be accepted;
- source-bound timing and health must be explicit rather than implicit.

This cost is accepted because it removes a correctness problem at the foundation instead of hiding it with model thresholds or hardware-specific patches.
