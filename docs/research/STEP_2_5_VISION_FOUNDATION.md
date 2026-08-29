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

### OpenCV + DirectShow

Measured result on the actual Pocket 3:

- MSMF 1280x720: 5/5 open/read success, ~2.96 s average open-to-first-frame;
- MSMF 1920x1080: 4/5 first-read success, ~4.834 s average, one grab failure;
- DSHOW 1280x720: 5/5 success, ~0.968 s average;
- DSHOW 1920x1080: 5/5 success, ~0.847 s average;
- DSHOW 1280x720 sustained: 300/300 frames, 0 failures, ~29.34 FPS.

Decision: OpenCV + DirectShow as the initial Pocket 3 adapter path, backend configurable. 1280x720 is the initial low-latency default; 1080p remains configurable for later end-to-end evaluation.

### Buffering

Realtime following values freshness over completeness. If inference cannot process every captured frame, JARVIS should process the newest available frame rather than build latency by queueing all frames.

Decision: single latest-frame slot / bounded overwrite semantics.

## PTZ Research

`duvc-ctl` already works on the real Pocket 3 through Windows camera control interfaces.

Decision: `ADOPT + WRAP` for the Pocket 3 adapter. Core logic sees a JARVIS `PtzController` and capability/range model, never `duvc-ctl` types.

## Detector Research

### RF-DETR Nano

Measured on the actual Windows + RTX 5060 Ti + Pocket 3 system using native PyTorch CUDA and BF16:

- mean latency: 36.97 ms;
- median latency: 36.65 ms;
- p95 latency: 41.96 ms;
- inference rate: 27.05 FPS;
- peak allocated VRAM: 114.8 MiB;
- warm-start load + optimize: 3.716 s in the tested process.

Controlled same-clip quality test on a 900-frame, 1280x720 Pocket 3 recording:

- person coverage at confidence 0.25: 100%;
- person coverage at confidence 0.50: 100%;
- longest miss streak at both thresholds: 0 frames;
- mean positive person confidence: 0.9514;
- median positive person confidence: 0.9570.

Status: `SELECT` initial detector.

### RF-DETR Small

Measured performance:

- mean latency: 40.67 ms;
- median latency: 40.07 ms;
- p95 latency: 45.47 ms;
- inference rate: 24.59 FPS;
- peak allocated VRAM: 129.3 MiB in the isolated performance run.

Controlled same-clip quality:

- person coverage at confidence 0.25: 100%;
- person coverage at confidence 0.50: 100%;
- longest miss streak at both thresholds: 0 frames;
- mean positive person confidence: 0.9601;
- median positive person confidence: 0.9648;
- disagreement frames vs Nano at confidence 0.50: 0.

Status: `DO NOT SELECT` initially. It showed no continuity/coverage improvement over Nano and did not justify slower throughput/higher resource use.

### RT-DETRv4-S

Measured performance:

- mean latency: 56.97 ms;
- median latency: 56.15 ms;
- p95 latency: 65.29 ms;
- inference rate: 17.55 FPS;
- peak allocated VRAM: 133.2 MiB;
- model load: ~0.569 s after checkpoint availability.

The tested native PyTorch path also required a benchmark-wrapper workaround because a cached positional embedding remained on CPU while the model moved to CUDA.

Status: `REJECT` initial detector path.

### Ultralytics YOLO26

Technically strong, but the standard Ultralytics distribution uses AGPL-3.0 with a separate Enterprise path. Strong permissive alternatives already meet the need.

Status: `REJECT` default Step 2.5 dependency.

## Inference Runtime Research

### Direct native Python/PyTorch CUDA

PyTorch 2.13.0 + CUDA 13.2 was validated on the RTX 5060 Ti with a real CUDA matrix multiplication. RF-DETR BF16 inference passed sustained live and recorded-clip tests.

Status: `ADOPT` initial production runtime.

### TensorRT

Potentially useful for optimization but adds conversion/runtime complexity.

Status: `DEFER`; selected detector already meets the initial real-time direction.

### Roboflow Inference

Useful later for distributed/multi-camera/server workflows, but unnecessary for the current one-camera local slice.

Status: `DEFER`.

## Tracker Research

### ByteTrack

Roboflow `trackers` 2.6.0 ByteTrack was tested against the exact same cached RF-DETR Nano person detections as BoT-SORT.

Full rate (~30 FPS), 900 processed frames:

- confirmed-track coverage: 99.89%;
- mean tracker latency: 0.345 ms;
- p95 tracker latency: 0.479 ms;
- primary-person ID switches: 0;
- longest same primary ID run: 899 frames;
- one dominant track ID for 899 frames.

Stress rate (~15 FPS), 450 processed frames using original timestamps:

- confirmed-track coverage: 99.78%;
- mean tracker latency: 0.366 ms;
- p95 tracker latency: 0.493 ms;
- primary-person ID switches: 0;
- longest same primary ID run: 449 frames;
- one dominant track ID for 449 frames.

Status: `SELECT` initial tracker.

### BoT-SORT + Camera Motion Compensation

Tested with `sparseOptFlow` CMC and the same detections/frames.

Full rate (~30 FPS), 900 processed frames:

- confirmed-track coverage: 99.89%;
- mean tracker latency: 8.843 ms;
- p95 tracker latency: 9.597 ms;
- primary-person ID switches: 0;
- longest same primary ID run: 899 frames.

Stress rate (~15 FPS), 450 processed frames:

- confirmed-track coverage: 99.78%;
- mean tracker latency: 8.908 ms;
- p95 tracker latency: 9.663 ms;
- primary-person ID switches: 0;
- longest same primary ID run: 449 frames.

BoT-SORT+CMC produced no measured continuity benefit over ByteTrack on the controlled workload while adding ~8.5 ms/frame tracker overhead.

Status: `DO NOT SELECT` initially. Reconsider only if future real multi-person occlusion or stronger camera motion produces ByteTrack ID fragmentation.

## Target Selection Research

A tracker only supplies tracks; it must not decide what JARVIS cares about.

JARVIS `TargetManager` owns:

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

Initial deterministic JARVIS follow policy uses:

- horizontal/vertical dead zones;
- bounded proportional gain;
- confidence requirement;
- maximum command limits;
- immediate idle/no-command on target uncertainty/loss.

PID remains unjustified until physical gimbal behavior shows proportional control is insufficient.

Decision: `BUILD` simple proportional/dead-zone controller first.

## Privacy

Step 2.5 must not persist room video by default. Benchmark clips are development artifacts outside the repository. Model weights, raw frames, personal face datasets, and generated logs are not repository content.

The controlled comparison clip contained 900 frames at 1280x720 and was captured outside the repository strictly for local benchmarking.

## Measured Benchmark Matrix

Completed on the actual Windows + RTX 5060 Ti 8 GB + Pocket 3 setup:

- capture backend reliability;
- capture resolution/FPS;
- native CUDA viability;
- detector latency/effective Hz;
- detector same-clip person continuity/coverage;
- detector VRAM allocation;
- detector startup behavior;
- tracker ID continuity;
- tracker skipped-frame stress behavior;
- tracker latency;
- moving-camera clip behavior.

Still required before Step 2.5 human acceptance:

- integrated end-to-end frame age/latency;
- CPU/RAM/GPU/VRAM in the complete loop;
- startup/shutdown behavior for the integrated runtime;
- camera disconnect/reopen behavior;
- long-run resource stability;
- Pocket 3 PTZ adapter production implementation;
- physical closed-loop target-follow behavior;
- target-loss-to-stop behavior;
- multi-person no-random-switch acceptance.

## Technology Decisions Summary

| Area | Decision |
| --- | --- |
| Camera contract | BUILD JARVIS boundary |
| OpenCV capture | WRAP; DSHOW selected for Pocket 3 |
| Pocket 3 PTZ | ADOPT + WRAP `duvc-ctl` |
| Detector contract | BUILD JARVIS boundary |
| RF-DETR Nano | SELECT, BF16 native PyTorch/CUDA |
| RF-DETR Small | NOT SELECTED initially |
| RT-DETRv4-S | REJECT initial path |
| YOLO26 | REJECT default due licensing tradeoff |
| Direct PyTorch/CUDA | ADOPT |
| TensorRT | DEFER |
| Roboflow Inference server | DEFER |
| Tracker contract | BUILD JARVIS boundary |
| ByteTrack | SELECT initial tracker |
| BoT-SORT + CMC | NOT SELECTED initially; reevaluate if real continuity fails |
| TargetManager | BUILD |
| FollowController | BUILD |
| Multi-camera registry | DEFER |
| Generic VisionEventEngine | DEFER |
| Generic resource manager | DEFER |
| Face/OCR/gesture/VLM/memory | DEFER |

## Selected Step 2.5 Vertical Slice

```text
CameraSource
-> latest frame
-> RF-DETR Nano BF16 adapter
-> canonical Detection[]
-> ByteTrack adapter
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

Step 2.5 is successful only when the selected target follows smoothly enough for real use, another person does not trigger random target switching, target loss stops movement safely, resources clean up correctly, and measured performance remains stable on the actual machine.
