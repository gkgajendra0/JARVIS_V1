# Step 3 — Sensor Fabric Architecture Research

Status: **PROPOSED ARCHITECTURE — DOCUMENTATION/RESEARCH ONLY — NO RUNTIME IMPLEMENTATION ACCEPTED**

Date: 2026-08-31

Base revision: `9f302bd` (`feature/step-3b-owner-identity-face-liveness`)

## Why this work exists

Phase 3B.11 active-speaker testing exposed a deeper architectural assumption that must be corrected before further threshold tuning: JARVIS currently treats camera and microphone capture largely as independent global resources, while future behavior requires multiple interchangeable physical sensor systems whose audio/video timing, capabilities, and health remain source-owned.

The real-machine Pocket 3 + DJI Mic Mini experiment proved that synchronized audio/video can produce healthy active-speaker behavior offline, while the live JARVIS path showed unstable alignment/cadence and conversation degradation when the Pocket 3 audio endpoint was promoted directly into the existing voice path. The correct response is not another local patch. The sensor boundary itself must become explicit.

This proposal deliberately preserves all accepted Step-3 authority and evidence invariants. It changes how sensory evidence is acquired and orchestrated, not what that evidence is allowed to authorize.

## Permanent design principle

JARVIS must not be built around one global `camera` and one global `microphone`.

JARVIS owns a **Sensor Fabric** containing physical sensor sources. A source advertises capabilities and, when it is an audio-visual source, owns its paired audio/video streams, timebase relationship, synchronization health, and source identity.

Conceptual source contract:

```text
SensorSource
- source_id
- physical_device_identity
- capabilities
- health
- lifecycle

AVSource extends SensorSource
- video_stream
- paired_audio_stream
- source timestamps / clock mapping
- synchronization health
- optional PTZ / fixed-camera / IR / depth capabilities
```

The exact Python API is intentionally not frozen by this research document. The invariant is the source-owned boundary, not a particular class shape.

## Physical source examples

### Pocket 3 source

```text
Pocket3AVSource
├── RGB video: OsmoPocket3
├── paired audio: Pocket 3 USB audio endpoint
│   └── may contain DJI Mic Mini input when paired/active
├── PTZ/gimbal capability
├── zoom capability
└── source synchronization state
```

### Lenovo fixed webcam source

When the planned fixed Lenovo webcam is physically available and its exact capabilities are verified:

```text
LenovoAVSource
├── Lenovo RGB video
├── Lenovo paired microphone
├── fixed monitor-relative geometry
└── discovered/verified capabilities only
```

No IR/depth/gaze capability is assumed merely from product-family naming; each capability must be verified on the exact hardware.

### Future sources

The same contract must admit future depth cameras, smart glasses, room cameras, microphones, or other sensors without rewriting the perception stack.

## Source pairing invariant

Any audio-visual inference that depends on temporal actor correlation must use audio paired with the exact visual source being scored, unless a separately accepted cross-device synchronization/calibration boundary exists.

Accepted target rule:

```text
Lenovo video + Lenovo paired audio     -> valid candidate AV evidence
Pocket3 video + Pocket3 paired audio   -> valid candidate AV evidence
Lenovo video + Pocket3 audio           -> invalid by default
Pocket3 video + Lenovo audio           -> invalid by default
```

If paired audio disappears or synchronization health becomes insufficient, audio-visual inference returns `INSUFFICIENT`/`UNAVAILABLE`; JARVIS must not silently substitute another microphone.

## Interaction source vs observation source

JARVIS needs two different concepts.

### Interaction source

The active interaction source is the source currently responsible for human/JARVIS interaction context. It may provide:

- person/face/liveness context;
- attention/gesture evidence;
- paired microphone audio;
- active-speaker evidence;
- ordinary conversation input where accepted.

A fixed Lenovo webcam may become the normal desk interaction source once available and accepted.

### Observation source

An observation source is selected to answer a perception request. It need not become the interaction source.

Example:

```text
OWNER at desk, Lenovo remains interaction source
        +
"Jarvis, look at this" + pointing at circuit board
        ↓
Lenovo supplies person/gesture/context
Pocket3 is selected as PTZ observation source for close inspection
```

Moving the Pocket 3 to inspect an object must not automatically switch the conversation microphone or destroy the established interaction source.

## Sensor Orchestrator

JARVIS needs a JARVIS-owned orchestration layer that receives semantic perception needs rather than raw device commands.

Example input:

```text
PerceptionRequest:
  intent = inspect_object
  referent = scene_object_12
  requirements = fine_visual_detail
```

The orchestrator evaluates:

- source health;
- source capabilities;
- visibility/coverage;
- PTZ availability;
- interaction continuity;
- synchronization requirements;
- privacy/safety constraints;
- expected cost/latency.

It chooses the least-disruptive healthy source capable of satisfying the request.

The reasoning model must not directly manipulate Windows device indices or invent device capabilities.

## Referential grounding and attention

Natural commands such as:

```text
"Jarvis, look at this."
"What is this?"
"Look behind me."
```

require explicit referential grounding rather than hard-coded camera selection.

Target evidence fusion:

```text
language reference
+ person track
+ hand/arm/index-finger geometry
+ gaze/head orientation when available
+ visible object candidates
+ scene/world context
        ↓
referent hypothesis
```

If one referent is sufficiently clear, JARVIS proceeds. If multiple plausible referents remain, JARVIS asks a short clarification rather than moving sensors blindly.

Mature primitives should be reused for landmarks/pose/gesture. JARVIS owns the contextual grounding and orchestration policy.

## Scene / world model boundary

Perception providers should not merely emit unrelated detections. JARVIS needs a bounded scene representation containing relationships such as:

```text
OWNER track
├── right hand points toward object_12
├── gaze/head orientation toward desk region
└── currently associated with interaction source

object_12
├── candidate class: circuit board
├── visible in Lenovo source
└── better inspection path available through Pocket3 PTZ
```

The world model is a perception/context substrate, not an authority source.

## Source switching

Promoting a new interaction source is a security-sensitive context transition.

A source switch must invalidate or reset source-bound temporal evidence rather than stitch it across devices. This includes, where applicable:

- active-speaker windows;
- source-bound face/liveness temporal windows;
- attention/gaze windows;
- source-specific AEC state;
- source-specific synchronization state;
- audio turn windows tied to the old source.

Cross-source continuity may support UX hypotheses (for example, likely same physical person), but security/trust evidence must be freshly corroborated on the new accepted source.

## Device discovery and physical pairing

Research indicates Windows Device Container IDs can group multiple functions of one physical device. JARVIS should evaluate `DEVPKEY_Device_ContainerId`/stable endpoint metadata as the primary physical-device identity and pairing mechanism rather than relying on mutable PortAudio indices or friendly-name matching alone.

Expected approach:

```text
Windows PnP / endpoint discovery
        ↓
physical device/container identity
        ↓
video + paired audio functions
        ↓
SensorRegistry
```

If hardware does not expose reliable physical grouping, JARVIS may use an explicit persisted pairing override that is user-reviewed and device-identity bound. Silent heuristic cross-device pairing is not acceptable for AV-sensitive evidence.

Reference:
- https://learn.microsoft.com/windows-hardware/drivers/install/devpkey-device-containerid

## Capture and timing foundation

Research indicates GStreamer is a strong candidate for the permanent Windows AV capture/timing layer because it provides:

- Windows Media Foundation video capture;
- WASAPI audio capture;
- clocked multimedia pipelines;
- timestamped buffers;
- clock slaving/resampling mechanisms for live audio;
- a mature way to expose buffers to JARVIS without replacing downstream perception models.

Candidate architecture:

```text
one clocked pipeline per AVSource

video source -> JARVIS video consumer
paired audio -> JARVIS audio consumer
        ↓
source-owned timing + synchronization diagnostics
```

GStreamer is a candidate foundation and must pass a bounded real-machine bake-off before adoption. The existing accepted OpenCV/LiveKit capture paths remain the known-good baseline until replacement is proven.

References:
- https://gstreamer.freedesktop.org/documentation/additional/design/synchronisation.html
- https://gstreamer.freedesktop.org/documentation/wasapi2/wasapi2src.html
- https://gstreamer.freedesktop.org/documentation/audio/gstaudiobasesrc.html

## Provider boundaries

Sensor Fabric must not hard-code one perception implementation. Mature providers remain replaceable behind JARVIS-owned contracts.

Candidate provider families include:

- existing RF-DETR tracking/object path;
- YuNet/SFace identity;
- MiniFAS passive liveness;
- MediaPipe hand/pose/gesture primitives;
- Grounding DINO or equivalent open-vocabulary grounding on demand;
- LR-ASD active-speaker provider;
- NVIDIA Maxine active-speaker/gaze/body providers as benchmark challengers where platform/license/runtime fit is acceptable.

No provider output directly authorizes an action.

## Permanent authority invariant

This architecture does not change the accepted Step-3 trust/authority separation.

```text
sensor selection        != permission
face match              != permission
liveness                != permission
speaker match           != permission
active-speaker result   != permission
attention/gaze          != permission
pointing/referent       != permission
model confidence        != permission
```

Consequential authority remains proposal/policy/approval bound through the accepted Step-3A architecture.

## What this proposal intentionally does not do

- It does not modify the current runtime.
- It does not make GStreamer accepted merely because it is mature.
- It does not make NVIDIA Maxine accepted merely because compatible APIs exist.
- It does not promote any LR-ASD threshold.
- It does not change T2/T3 semantics.
- It does not enable persistent speaker learning.
- It does not assume the future Lenovo webcam's exact capabilities before hardware verification.

## Architecture acceptance criteria

Before this proposal becomes `CURRENT_ARCHITECTURE`:

1. exact source-owned AV contract is implemented behind compatibility adapters;
2. current known-good JARVIS remains runnable unchanged during migration;
3. Pocket 3 is implemented as the first source without losing accepted vision/identity behavior;
4. paired source timing is measured and synchronization failure is observable/fail-closed;
5. no cross-device AV mixing occurs implicitly;
6. source switching explicitly invalidates source-bound evidence;
7. existing Step-3 security invariants remain covered by tests;
8. real-machine acceptance demonstrates no regression in normal JARVIS conversation/vision before old capture ownership is retired;
9. the future Lenovo source plugs into the same contract rather than requiring another architecture rewrite.

## Decision status

**PROPOSED.**

An ADR should be written only after human review/acceptance of this research and the migration plan. `docs/CURRENT_ARCHITECTURE.md` must remain unchanged until implementation and real-machine acceptance are complete.
