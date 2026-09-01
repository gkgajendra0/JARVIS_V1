# Step 3 — Sensor Fabric Safe Migration Plan

Status: **PROPOSED EXECUTION PLAN — NO RUNTIME MIGRATION STARTED**

Date: 2026-08-31

Base known-good revision: `9f302bd`

Research branch: `research/step-3-sensor-fabric-architecture`

## Objective

Replace the current implicit global camera/microphone assumptions with a source-owned Sensor Fabric without regressing any currently accepted JARVIS capability.

The migration must behave like a controlled subsystem replacement, not a rewrite.

## Non-negotiable migration rule

**The known-good runtime remains runnable until every replacement slice has independently passed automated tests, real-machine testing, and explicit human acceptance.**

No accepted provider/path is deleted merely because a new path compiles or passes unit tests.

## Branching strategy

The project does not use a permanent `develop` branch. Keep the existing protected-main + focused-branch model.

Current dependency chain:

```text
main
  └── feature/step-3b-owner-identity-face-liveness
          └── research/step-3-sensor-fabric-architecture
```

This research branch is documentation/research only.

After architecture acceptance, create a separate implementation branch from the then-current accepted Step-3B head, for example:

```text
feature/step-3-sensor-fabric-foundation
```

PR #10 remains draft/unmerged until its own protected-main acceptance decision. This migration plan does not authorize merging PR #10 or `main`.

## Known-good baseline

The migration baseline is the current accepted runtime behavior at `9f302bd`, including:

- current wake/runtime lifecycle;
- current LiveKit/provider conversation path;
- accepted Pocket 3 visual capture/tracking/PTZ behavior;
- accepted OWNER face/liveness path;
- speaker shadow infrastructure;
- current active-speaker shadow implementation;
- current authority/security boundaries;
- `jarvis-dev` supervised Git-update workflow.

Baseline behavior must be captured in tests/logged real-machine acceptance before any old path is retired.

## Compatibility-first architecture

Every new foundation is introduced behind JARVIS-owned contracts and adapters.

Target transition pattern:

```text
current provider/path -----------------------┐
                                             ├── JARVIS-owned contract
new provider/path (disabled/shadow first) ---┘
```

Only after the new path passes acceptance does it become primary. The old path remains available for rollback until an explicit cleanup slice.

## Proposed migration slices

### Slice 0 — Architecture/ADR gate

Documentation only.

Deliverables:

- Sensor Fabric research;
- synchronized AV/full-duplex audio research;
- migration plan;
- unresolved questions and provider bake-offs;
- human architecture review;
- ADR only after acceptance.

Exit criteria:

- no runtime files modified;
- architecture invariants explicitly accepted;
- implementation branch created only after approval.

### Slice 1 — Sensor domain model

Implement JARVIS-owned types/contracts only:

- `SensorSource` / `AVSource` concepts;
- capabilities;
- source identity;
- health state;
- synchronization-health contract;
- interaction-source vs observation-source vocabulary.

Do not replace physical capture yet.

Exit criteria:

- pure unit tests;
- no current runtime behavior change;
- no device opening by the new model.

### Slice 2 — SensorRegistry and Windows physical-device discovery

Implement stable discovery/pairing metadata using mature Windows device identity where available.

Requirements:

- no numeric-index persistence as physical identity;
- explicit physical container/endpoint identity where available;
- deterministic ambiguity handling;
- explicit user-reviewed override for devices that cannot be reliably paired;
- fail closed for AV-sensitive pairing ambiguity.

Exit criteria:

- Pocket 3 endpoints correctly discovered/paired on real machine;
- current runtime still uses old capture path;
- no automatic promotion to primary input.

### Slice 3 — Pocket3 source adapter over current accepted capture

Before introducing GStreamer, wrap the current Pocket 3 video/audio identity behind the new source contract using compatibility adapters.

Purpose:

- prove the abstraction without changing the physical capture technology;
- bind existing accepted visual evidence to a source identity;
- expose paired-audio identity even if the existing voice runtime still owns conversation capture.

Exit criteria:

- accepted Pocket 3 vision/identity behavior unchanged;
- source identity visible in diagnostics;
- no LR-ASD threshold change;
- no conversation input change.

### Slice 4 — GStreamer AV capture proof-of-concept in shadow

Build a disabled/shadow GStreamer source for Pocket 3.

Requirements:

- one source-owned video/audio graph where practical;
- in-memory outputs only;
- timestamps/clock diagnostics;
- no duplicate authority evidence;
- no replacement of current VisionService/LocalAudioRuntime yet.

Benchmark against current path:

- camera FPS/cadence;
- unique frames;
- audio continuity;
- A/V offset/drift;
- CPU/GPU cost;
- startup/recovery behavior.

Exit criteria:

- stable real-machine capture;
- synchronization health observable;
- no regression to existing JARVIS because shadow path is non-authoritative/non-primary.

### Slice 5 — AV synchronization health

Implement source-owned timing validation and fail-closed coverage rules.

Requirements:

- offset/drift/gap diagnostics;
- track/session/source continuity checks;
- active-speaker window builder consumes only healthy paired-source evidence;
- unhealthy source becomes `INSUFFICIENT`, never silently substituted.

Exit criteria:

- deterministic tests for gaps, drift, discontinuity and source changes;
- real Pocket 3 synchronized recording reproduces known healthy behavior.

### Slice 6 — Render-reference and EchoCanceller provider boundary

Separate JARVIS physical output from echo-provider implementation through an explicit render-reference bus.

Providers:

- current WebRTC/LiveKit APM as primary candidate;
- NVIDIA Maxine AEC only as bounded challenger if needed.

Requirements:

- no microphone muting during playback;
- output/mic pair-specific health/state;
- measurable diagnostics;
- existing conversation path remains selectable.

Exit criteria:

- JARVIS playback-only does not become a user turn in accepted hardware configuration;
- real user barge-in remains functional;
- failure is observable and recoverable.

### Slice 7 — JARVIS-owned activity controller

Move near-end activity truth above the realtime-provider adapter.

Requirements:

- local VAD/near-end activity state;
- distinguish at least user speech, echo-only, double-talk/ambiguous where evidence permits;
- provider-neutral activity contract;
- Gemini manual activity mode evaluated first;
- provider adapter remains swappable.

Exit criteria:

- no false Gemini interruption from JARVIS speaker playback in accepted scenario;
- deliberate real-user interruption works;
- ordinary turn latency remains acceptable.

### Slice 8 — Active-speaker provider bake-off on synchronized source

Only after source timing and audio activity are healthy, resume 3B.11 scoring.

Providers:

- LR-ASD existing implementation;
- NVIDIA Maxine Active Speaker Detection challenger if runtime/license/dependency fit is acceptable.

Required scenarios retain the current security test set:

- OWNER speaking;
- JARVIS playback only;
- TV/phone/off-camera speech;
- OWNER playback attack;
- multiple visible people;
- other person speaking;
- overlap;
- temporary head/face loss;
- timing discontinuity.

No production threshold before measured separation.

Exit criteria:

- selected provider has stable real-machine distributions;
- active-speaker result binds exact source/session/track/turn;
- prototype admission still remains disabled until acceptance.

### Slice 9 — Interaction-source switching

Implement controlled handoff between complete interaction sources.

Requirements:

- source switch resets source-bound temporal evidence;
- no cross-source AV stitching;
- conversation continuity handled separately from security evidence continuity;
- fail closed if target source is unhealthy.

Pocket 3 is the first real source. Lenovo testing begins only when exact hardware is available.

### Slice 10 — Lenovo source integration

When hardware arrives:

- discover physical source/pairing;
- validate paired microphone and video timing;
- evaluate it as fixed interaction source;
- verify exact camera capabilities rather than assuming product claims;
- run the same full-duplex and active-speaker acceptance suite.

Only then consider making Lenovo the default desk interaction source.

### Slice 11 — Attention / pointing / referential grounding

With a fixed camera available, resume the deferred attention work.

Reuse mature pose/hand/gaze primitives behind provider contracts. Implement JARVIS-owned contextual grounding and sensor orchestration.

Acceptance target:

```text
OWNER points at an object and says "Jarvis, look at this"
        ↓
JARVIS resolves the referent or asks a short clarification
        ↓
selects/moves the best healthy observation source
        ↓
inspects the intended object
        ↓
interaction source remains stable unless an explicit handoff is needed
```

## Parallel-run and shadow rules

During migration, a new provider may run in shadow only if doing so does not introduce conflicting physical-device ownership or material performance instability.

Shadow outputs:

- are diagnostic only;
- do not grant trust;
- do not authorize actions;
- do not admit persistent speaker prototypes;
- are discarded after bounded analysis unless explicitly accepted research evidence is recorded without raw sensitive media.

## Rollback strategy

Each implementation slice must have a single-revision rollback point.

Rules:

- commit bounded changes;
- push only after local tests;
- use `jarvis-dev` on intentional implementation branches where appropriate;
- spoken approval is required before supervised update;
- startup readiness failure restores last-known-good revision;
- runtime behavioral failure means revert/promote old provider, not continue layering patches on a broken primary path.

Do not delete the old provider/path in the same slice that first promotes the new provider.

## Testing pyramid

Every slice should pass progressively stronger gates.

```text
static/type/lint tests
        ↓
unit tests
        ↓
integration tests with fakes/recorded metadata
        ↓
real-machine shadow run
        ↓
real hardware adversarial/edge scenarios
        ↓
human acceptance
        ↓
promotion
```

A unit-test pass is never sufficient for camera/microphone/synchronization/AEC acceptance.

## Required regression suite

Before promotion of any new foundation, verify no regression in:

- wake detection;
- normal conversation quality;
- intentional barge-in;
- session exit;
- Tribit output;
- accepted Pocket 3 vision/tracking/PTZ;
- OWNER face/liveness evidence;
- Windows lock invalidation;
- speaker-shadow quality gating;
- authority/policy invariants;
- privacy/non-persistence constraints.

## Data/privacy rules during migration

- no raw audio/video persistence by default;
- no raw biometric persistence;
- recorded diagnostic media requires explicit bounded test intent;
- logs prefer timing/health/statistics over content;
- provider experiments do not create permanent owner voiceprints;
- temporary research assets stay outside source control unless safe/non-sensitive.

## What must not happen

- no big-bang rewrite;
- no direct replacement of VisionService and LocalAudioRuntime in one slice;
- no hard-coded future Lenovo capabilities;
- no LR-ASD threshold tuning on known-bad timing;
- no microphone muting as the permanent echo solution;
- no silent use of a different microphone when paired AV audio is unhealthy;
- no automatic branch/main merge;
- no modification of `CURRENT_ARCHITECTURE.md` until implementation and human acceptance.

## Documentation promotion rule

Research documents describe proposed/rejected/evaluated architecture.

An ADR freezes an accepted design decision before implementation when appropriate.

`CURRENT_ARCHITECTURE.md` is updated only after the corresponding behavior is implemented and human-accepted.

`CURRENT_PLAN.md` should be reconciled after this architecture proposal is reviewed so 3B.11 explicitly pauses threshold promotion until the prerequisite Sensor Fabric/audio foundation is accepted.

## Immediate next gate

1. human review of the three Sensor Fabric research/migration documents;
2. resolve any architecture concerns;
3. write/accept ADR for source-owned Sensor Fabric architecture;
4. reconcile `CURRENT_PLAN.md`;
5. create implementation branch;
6. begin Slice 1 only.

Until those steps occur, current JARVIS remains the known-good implementation.
