# JARVIS V1 Current Plan

## Active Step

**Step 2.5 — Vision Sensor & Active Target Tracking Foundation**

## Current Stage

**TECHNOLOGY SELECTION COMPLETE — INTEGRATED IMPLEMENTATION NEXT**

Step 2 was human-accepted on 2026-08-29. Step 3 research began immediately afterward, but the human owner explicitly approved a bounded roadmap interlude to establish JARVIS visual sensing and active target tracking before Step 3 implementation continues.

Step 3 is paused, not discarded. Its identity/trust/authority work resumes after Step 2.5 human acceptance.

## Objective

Build the smallest reusable visual foundation that lets JARVIS:

- own one camera capture path;
- receive fresh frames without unbounded backlog;
- detect people with a replaceable detector adapter;
- maintain stable tracks with a replaceable tracker adapter;
- deterministically lock one target;
- convert target position into bounded movement intent;
- control the proven DJI Pocket 3 PTZ path through a replaceable adapter;
- expose small canonical visual state for later conversation and Step-3 identity evidence.

## Architectural Rules

- JARVIS owns canonical `Detection`, `Track`, target state, movement policy, and visual state.
- External detector/tracker SDK types stay behind adapters.
- The detector and tracker never command hardware directly.
- Camera capture and PTZ movement are separate responsibilities even when one physical device provides both.
- Vision evidence is not authentication or permission.
- One camera owner uses latest-frame semantics; no unbounded frame queues.
- Do not create speculative registries, event buses, model resource managers, or multi-camera orchestration before a real second requirement exists.
- Do not commit model weights, personal face data, raw captures, generated logs, or benchmark garbage.

## Proven Hardware Evidence

The actual Windows + DJI Osmo Pocket 3 setup has established:

- Pocket 3 USB webcam mode works;
- Windows exposes the device as a camera;
- Python can access camera-control properties;
- `duvc-ctl` can physically pan, tilt, and zoom the gimbal;
- reported device-control ranges were pan `-35..215`, tilt `-90..90`, zoom `100..400`;
- OpenCV DirectShow sustained 1280x720 capture at ~29.34 FPS with 300/300 successful frames.

These PTZ ranges are adapter/device values, not assumed physical degrees. Production code must query capabilities dynamically.

## Frozen Technology Decisions

### Capture

- `CameraSource` — JARVIS-owned contract.
- OpenCV — selected capture adapter mechanism.
- DirectShow (`CAP_DSHOW`) — selected initial Pocket 3 Windows backend from measured MSMF-vs-DSHOW evidence.
- 1280x720 — initial low-latency tracking mode.
- latest-frame / bounded-overwrite semantics — mandatory.

### PTZ

- `PtzController` — JARVIS-owned contract.
- `duvc-ctl` — selected and wrapped for Pocket 3 pan/tilt/zoom.

### Detector

- `ObjectDetector` — JARVIS-owned contract.
- RF-DETR Nano — selected initial detector.
- native PyTorch/CUDA BF16 — selected initial inference mode.

Measured RF-DETR Nano evidence on RTX 5060 Ti:

- 36.97 ms mean detector latency;
- 41.96 ms p95;
- 27.05 FPS;
- 114.8 MiB peak allocated VRAM;
- 100% person coverage at confidence 0.25 and 0.50 across the controlled 900-frame Pocket 3 clip;
- zero miss streaks on that controlled clip.

RF-DETR Small matched coverage but was slower; RT-DETRv4-S was materially slower and required an upstream native-PyTorch workaround.

### Tracker

- `Tracker` — JARVIS-owned contract.
- Roboflow `trackers` ByteTrack — selected initial tracker.

Controlled tracker evidence using the exact same cached RF-DETR Nano detections:

Full rate (~30 FPS):

- ByteTrack: 99.89% confirmed coverage, 0 ID switches, 899-frame continuous primary ID, ~0.345 ms mean / 0.479 ms p95 tracker latency;
- BoT-SORT + CMC: identical continuity, ~8.843 ms mean / 9.597 ms p95.

Stress rate (~15 FPS using original timestamps):

- ByteTrack: 99.78% confirmed coverage, 0 ID switches, 449-frame continuous primary ID, ~0.366 ms mean / 0.493 ms p95;
- BoT-SORT + CMC: identical continuity, ~8.908 ms mean / 9.663 ms p95.

Decision: ByteTrack wins because CMC produced no measured continuity benefit on the current workload while adding substantial overhead.

### JARVIS-owned policy

- `TargetManager` — deterministic explicit target lock/loss behavior.
- `FollowController` — bounded proportional/dead-zone policy.
- no automatic person switching;
- no movement on missing/uncertain target.

## Deferred / Not Selected for Step 2.5

- TensorRT unless integrated measurements show a real need;
- Roboflow Inference server as a mandatory runtime dependency;
- RF-DETR Small as the initial detector;
- RT-DETRv4-S as the initial detector;
- BoT-SORT + CMC as the initial tracker;
- YOLO26 as default due licensing tradeoff;
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

## Selected Vertical Slice

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

## Implementation Sequence

Completed:

1. Record Step 2.5 roadmap/research/ADR and preserve Step 3 as paused.
2. Implement provider-neutral canonical vision domain contracts and deterministic target/follow policy.
3. Benchmark OpenCV capture backend behavior on Pocket 3.
4. Validate native PyTorch/CUDA on the RTX 5060 Ti.
5. Benchmark detector candidates on real Pocket 3 footage and controlled same-clip quality input.
6. Benchmark ByteTrack vs BoT-SORT+CMC at full and skipped-frame rates.
7. Freeze capture/detector/tracker/runtime technology from measured evidence.

Next:

8. Reconcile production dependencies for RF-DETR/PyTorch/trackers without carrying benchmark-only packages.
9. Implement RF-DETR Nano detector adapter translating outputs into canonical `Detection` values.
10. Implement ByteTrack tracker adapter translating outputs into canonical `Track` values.
11. Implement Pocket 3 PTZ adapter with dynamic capability/range discovery and safe clamping.
12. Compose minimal `VisionRuntime` around latest-frame capture, detector, tracker, target manager, follow controller, and PTZ.
13. Add automated adapter/runtime failure, target-loss, cleanup, and recovery tests.
14. Measure integrated frame age, detector+tracker loop rate, CPU/RAM/GPU/VRAM, and target-loss-to-stop latency.
15. Validate camera disconnect/reopen and clean shutdown.
16. Run long-enough resource/thermal stability test.
17. Perform real human closed-loop target-follow acceptance tests.
18. Cleanup benchmark-only environment artifacts and reconcile documentation before merge.

## Initial Human Acceptance Scenarios

- selected person can be centered and followed left/right smoothly;
- another person entering does not cause random target switching;
- temporary occlusion does not cause immediate unsafe retargeting;
- target loss stops camera movement within a bounded interval;
- camera/PTZ failure degrades safely;
- no unbounded frame backlog or memory growth occurs;
- shutdown releases camera/PTZ resources cleanly;
- long-enough real use exposes no unacceptable thermal or runtime instability.

## Performance Evidence Still Required

Before final acceptance, measure the integrated runtime:

- frame age from capture to control decision;
- end-to-end detector + tracker effective rate;
- PTZ response behavior;
- CPU/RAM/GPU/VRAM use;
- target-loss-to-stop latency;
- dropped/stale frame behavior;
- startup/shutdown timing and resource release;
- disconnect/reopen behavior;
- long-run memory/resource stability.

Exact final acceptance gates should be frozen from the integrated baseline rather than invented before measurement.

## Step-3 Boundary

Step 2.5 may later expose presence or identity evidence, but it cannot grant trust or authority. The future relationship remains:

```text
Vision evidence
-> Step 3 identity/trust evaluation
-> future authorization decision
```

## Completion Gate

Step 2.5 is `DONE` only after measured technology selection, integrated implementation, automated validation, real Pocket 3 closed-loop use, human acceptance, cleanup, and documentation reconciliation.

## Immediate Next Action

Implement the selected RF-DETR Nano detector adapter, ByteTrack tracker adapter, and Pocket 3 PTZ adapter behind the already-defined JARVIS boundaries, then compose and validate the minimal `VisionRuntime`.
