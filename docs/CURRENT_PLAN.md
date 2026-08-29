# JARVIS V1 Current Plan

## Active Step

**Step 2.5 — Vision Sensor & Active Target Tracking Foundation**

## Current Stage

**IMPLEMENTATION STARTED — TECHNOLOGY BENCHMARKS STILL OPEN**

Step 2 was human-accepted on 2026-08-29. Step 3 research began immediately afterward, but the human owner explicitly approved a bounded roadmap interlude to establish JARVIS visual sensing and active target tracking before Step 3 implementation continues.

Step 3 is paused, not discarded. Its identity/trust/authority work resumes after Step 2.5 human acceptance.

## Objective

Build the smallest reusable visual foundation that lets JARVIS:

- own one camera capture path;
- receive fresh frames without unbounded backlog;
- consume replaceable person detections and tracks;
- deterministically lock one target;
- convert target position into bounded movement intent;
- control the proven DJI Pocket 3 PTZ path through a replaceable adapter;
- expose small canonical visual state for later conversation and Step-3 identity evidence.

## Architectural Rules

- JARVIS owns canonical `Detection`, `Track`, target state, movement policy, and visual state.
- External detector/tracker SDK types must stay behind adapters.
- The detector and tracker never command hardware directly.
- Camera capture and PTZ movement are separate responsibilities even when one physical device provides both.
- Vision evidence is not authentication or permission.
- One camera owner uses latest-frame semantics; no unbounded frame queues.
- Do not create speculative registries, event buses, model resource managers, or multi-camera orchestration before a real second requirement exists.
- Do not commit model weights, personal face data, raw captures, generated logs, or benchmark garbage.

## Proven Hardware Evidence

The actual Windows + DJI Osmo Pocket 3 setup has already established:

- Pocket 3 USB webcam mode works;
- Windows exposes the device as a camera;
- Python can access camera-control properties;
- `duvc-ctl` can physically pan, tilt, and zoom the gimbal;
- reported device-control ranges were pan `-35..215`, tilt `-90..90`, zoom `100..400`.

These ranges are adapter/device values, not assumed physical degrees. Production code must query capabilities dynamically.

## Technology Research Decisions

### Accepted now

- `CameraSource` — JARVIS-owned contract.
- OpenCV — initial capture adapter candidate; benchmark Windows Media Foundation vs DirectShow behavior on the real Pocket 3.
- `PtzController` — JARVIS-owned contract.
- `duvc-ctl` — adopted and wrapped for the proven Pocket 3 PTZ path.
- `ObjectDetector` — JARVIS-owned replacement boundary.
- `Tracker` — JARVIS-owned replacement boundary.
- `TargetManager` — JARVIS-owned deterministic target selection/lock.
- `FollowController` — JARVIS-owned bounded movement policy.

### Benchmark before freezing

Detector candidates:

- RF-DETR Nano;
- RF-DETR Small;
- RT-DETRv4-S.

Tracker candidates:

- ByteTrack baseline;
- BoT-SORT with camera-motion compensation as the primary moving-camera candidate.

Runtime candidate:

- direct native Python/PyTorch CUDA first;
- TensorRT only if measurements justify optimization;
- Roboflow Inference deferred unless it materially reduces complexity for later multi-camera/distributed workflows.

### Rejected/deferred for Step 2.5

- YOLO26 as the default dependency because the standard Ultralytics licensing path is unnecessarily restrictive for this project when strong permissive alternatives exist;
- full Roboflow Inference server as an initial mandatory runtime dependency;
- face recognition/authentication;
- OCR;
- pose/gesture/pointing;
- local/cloud VLM integration;
- visual memory;
- continuous recording;
- passive world awareness;
- multi-camera registry/fusion;
- generic vision event bus;
- generic GPU/model resource manager;
- HUD integration;
- Step-3 authority logic.

## Implementation Sequence

1. Record Step 2.5 roadmap/research/ADR and preserve Step 3 as paused.
2. Implement provider-neutral canonical vision domain contracts and deterministic target/follow policy.
3. Build isolated hardware/model benchmarks outside the normal runtime path.
4. Benchmark OpenCV capture backend behavior on Pocket 3.
5. Validate native PyTorch/CUDA on the RTX 5060 Ti.
6. Benchmark detector candidates on real Pocket 3 footage.
7. Benchmark ByteTrack vs BoT-SORT+CMC while the camera is stationary and moving.
8. Freeze exact production dependencies after measured results.
9. Implement Pocket 3 camera and PTZ adapters.
10. Implement selected detector/tracker adapters.
11. Compose minimal `VisionRuntime` using latest-frame semantics.
12. Run automated failure/recovery tests and all existing regression tests.
13. Perform real human target-follow acceptance tests.
14. Cleanup temporary benchmark artifacts and reconcile documentation before merge.

## Initial Human Acceptance Scenarios

- selected person can be centered and followed left/right smoothly;
- another person entering does not cause random target switching;
- temporary occlusion does not cause immediate unsafe retargeting;
- target loss stops camera movement within a bounded interval;
- camera/PTZ failure degrades safely;
- no unbounded frame backlog or memory growth occurs;
- shutdown releases camera/PTZ resources cleanly;
- long-enough real use exposes no unacceptable thermal or runtime instability.

## Performance Evidence To Capture

Before final acceptance, measure:

- capture FPS and frame age;
- detector latency and effective inference rate;
- tracker continuity / ID switches;
- PTZ response behavior;
- CPU/RAM/GPU/VRAM use;
- target-loss-to-stop latency;
- dropped/stale frame behavior;
- long-run memory/resource stability.

Exact numerical gates will be frozen after the real benchmark baseline rather than invented before measurement.

## Step-3 Boundary

Step 2.5 may later expose presence or identity evidence, but it cannot grant trust or authority. The future relationship remains:

```text
Vision evidence
-> Step 3 identity/trust evaluation
-> future authorization decision
```

## Completion Gate

Step 2.5 is `DONE` only after research, measured technology selection, approved architecture, implementation, automated validation, real Pocket 3 use, human acceptance, cleanup, and documentation reconciliation.

## Immediate Next Action

Implement the technology-neutral vision foundation on the feature branch while isolated hardware/model benchmarks determine the detector, tracker, and capture-backend winners. Do not add unbenchmarked ML dependencies to the production runtime.