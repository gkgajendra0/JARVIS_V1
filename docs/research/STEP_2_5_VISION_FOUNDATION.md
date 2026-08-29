# Step 2.5 Research — Vision Sensor & Active Target Tracking Foundation

Date: 2026-08-29

## Scope

This research covers the smallest vision foundation worth adding before Step 3 implementation resumes. It is intentionally narrower than full computer vision, passive world awareness, face authentication, OCR, gestures, VLM reasoning, or visual memory.

The target outcome is a reliable local loop:

```text
camera frame
-> person detection
-> tracking
-> deterministic target lock
-> bounded follow policy
-> PTZ movement
```

with replaceable technology boundaries.

## Existing Proven Evidence

On the actual Windows machine with DJI Osmo Pocket 3:

- USB webcam mode works;
- Windows exposes the camera feed;
- Python can access camera controls;
- `duvc-ctl` physically moves pan/tilt/zoom;
- reported device-control ranges were pan `-35..215`, tilt `-90..90`, zoom `100..400`;
- keyboard-driven PTZ movement was manually validated.

These device ranges must be dynamically discovered in production and are not treated as physical degrees.

## Architecture Principles

1. One authoritative camera owner.
2. Latest-frame semantics; stale video must not accumulate in a queue.
3. JARVIS-owned canonical detection/track/target state.
4. Provider/model SDK types stay behind adapters.
5. Detection/tracking never directly controls hardware.
6. Target selection is deterministic JARVIS logic.
7. PTZ transport is replaceable and separate from capture.
8. Vision evidence never becomes permission.
9. Build only the active slice; avoid speculative multi-camera registries/event buses/resource managers.
10. Measure actual Windows/Pocket 3/RTX 5060 Ti behavior before freezing performance-sensitive dependencies.

## Capture Research

### OpenCV

OpenCV remains the practical initial Python capture boundary because it can select Windows backends and is easy to benchmark. It should be wrapped behind `CameraSource` so no other component depends on `cv2.VideoCapture`.

### Windows Media Foundation vs DirectShow

Microsoft classifies DirectShow as legacy and recommends Media Foundation for new Windows media development. However, the actual Pocket 3 path has already proven DirectShow/UVC camera-control compatibility, and real OpenCV Media Foundation camera behavior can vary by device/driver.

Decision: benchmark both on the real camera. Prefer Media Foundation if it is equally reliable; allow DirectShow as an adapter-level compatibility choice. Neither backend becomes a JARVIS domain concept.

### Buffering

Realtime following values freshness over completeness. If inference cannot process every captured frame, JARVIS should process the newest available frame rather than build latency by queueing all frames.

Decision: single latest-frame slot / bounded overwrite semantics.

## PTZ Research

`duvc-ctl` already works on the real Pocket 3 through Windows camera control interfaces.

Decision: `ADOPT + WRAP` for the Pocket 3 adapter. Core logic sees a JARVIS `PtzController` and capability/range model, never `duvc-ctl` types.

## Detector Research

### RF-DETR

RF-DETR Nano/Small are strong current realtime candidates with permissive Apache-2.0 licensing for the core model family and direct Python use. The ecosystem also supports ONNX/TensorRT export if later optimization is justified.

Status: primary benchmark candidate.

### RT-DETRv4-S

RT-DETRv4 provides another current permissive real-time detector path with ONNX/TensorRT/PyTorch deployment options.

Status: comparison candidate.

### Ultralytics YOLO26

Technically strong, but the standard Ultralytics distribution uses AGPL-3.0 with a separate Enterprise licensing path for non-AGPL commercial/private embedding. JARVIS has credible permissive alternatives, so inheriting this licensing constraint is unnecessary.

Status: `REJECT` as the default Step-2.5 dependency. Reconsider only if future evidence shows a material technical advantage worth the licensing tradeoff.

## Inference Runtime Research

### Direct native Python/PyTorch CUDA

This is the smallest runtime path and the most debuggable starting point for one local camera and one detector.

Status: preferred initial production path if benchmarks are acceptable.

### TensorRT

Potentially useful for latency/VRAM optimization, but adds conversion/runtime complexity.

Status: `DEFER`; use only when measurements show a real need.

### Roboflow Inference

Roboflow Inference is mature and supports local/server workflows on Windows. It becomes more compelling with multiple cameras, distributed inference, remote streams, or reusable visual workflows.

For the current one-camera Step 2.5 slice, requiring a separate inference service/server would add lifecycle and dependency complexity that direct model integration does not need.

Status: `DEFER`, not rejected.

## Tracker Research

### ByteTrack

Simple, fast, proven detector-based multi-object tracking. Good baseline.

Status: benchmark baseline.

### BoT-SORT + Camera Motion Compensation

Pocket 3 actively pans/tilts, so the full frame moves when the camera moves. Camera-motion compensation is therefore directly relevant. BoT-SORT provides a stronger moving-camera candidate than plain ByteTrack.

Status: primary benchmark candidate.

Decision must be based on real ID continuity while the Pocket 3 is stationary and while it pans/tilts.

## Target Selection Research

A tracker only supplies tracks; it must not decide what JARVIS cares about.

JARVIS needs a small `TargetManager` that owns:

- explicit active track ID;
- lock/unlock state;
- last-seen timing;
- bounded missing-target state;
- no automatic switch to another person;
- deterministic lost-target result.

Initial Step 2.5 does not identify the owner. If several people are present, JARVIS must not guess identity.

Decision: `BUILD`.

## Follow-Control Research

Detector/tracker output must not directly issue motor commands.

A deterministic JARVIS follow policy converts target-center error into bounded PTZ movement. Initial policy should use:

- horizontal/vertical dead zones;
- hysteresis where needed;
- minimum command interval;
- maximum per-command movement;
- confidence requirement;
- device range clamps;
- immediate stop/no-command on target uncertainty/loss.

A PID controller is not justified until real gimbal behavior demonstrates proportional control is inadequate.

Decision: `BUILD` simple proportional/dead-zone controller first.

## Future Extension Compatibility

The architecture must make these later capabilities possible without implementing them now:

- fixed observer webcam;
- smart glasses / first-person camera;
- face detection/recognition as identity evidence;
- hand/pose/gesture/pointing;
- OCR;
- local/cloud VLM;
- recent visual buffer;
- multi-camera selection;
- visual memory;
- passive world awareness.

Future compatibility comes from narrow interfaces and canonical state, not empty registries/managers created in advance.

## Privacy

Step 2.5 must not persist room video by default. Benchmark clips, if captured manually, are development artifacts and must stay outside the normal committed runtime. Model weights, raw frames, personal face datasets, and generated logs are not repository content.

## Measured Benchmark Matrix Required

Before freezing detector/tracker/runtime technology, capture on the actual Windows + RTX 5060 Ti 8 GB + Pocket 3 setup:

- capture backend reliability;
- resolution/FPS;
- frame age/latency;
- detector latency and effective Hz;
- detector quality for near/far/partial/blur/low-light people;
- VRAM/RAM/CPU use;
- tracker ID switches;
- moving-camera continuity;
- startup/shutdown behavior;
- disconnect/reopen behavior;
- long-run resource stability.

## Technology Decisions Summary

| Area | Decision |
| --- | --- |
| Camera contract | BUILD JARVIS boundary |
| OpenCV capture | WRAP, benchmark MSMF vs DSHOW |
| Pocket 3 PTZ | ADOPT + WRAP `duvc-ctl` |
| Detector contract | BUILD JARVIS boundary |
| RF-DETR Nano/Small | BENCHMARK primary |
| RT-DETRv4-S | BENCHMARK comparison |
| YOLO26 | REJECT default due licensing tradeoff |
| Direct PyTorch/CUDA | ADOPT if benchmark passes |
| TensorRT | DEFER until justified |
| Roboflow Inference server | DEFER |
| Tracker contract | BUILD JARVIS boundary |
| ByteTrack | BENCHMARK baseline |
| BoT-SORT + CMC | BENCHMARK primary |
| TargetManager | BUILD |
| FollowController | BUILD |
| Multi-camera registry | DEFER |
| Generic VisionEventEngine | DEFER |
| Generic resource manager | DEFER |
| Face/OCR/gesture/VLM/memory | DEFER |

## Proposed Step 2.5 Vertical Slice

```text
CameraSource
-> latest frame
-> ObjectDetector
-> canonical Detection[]
-> Tracker
-> canonical Track[]
-> TargetManager
-> TargetState
-> FollowController
-> bounded movement intent
-> PtzController
-> Pocket 3
```

A minimal `VisionSnapshot` may expose camera health, tracks, active target, and PTZ state to later components. No event bus is required yet.

## Acceptance Direction

Step 2.5 is successful only when the selected target follows smoothly enough for real use, another person does not trigger random switching, target loss stops movement safely, resources clean up correctly, and measured performance is stable enough on the actual machine.
