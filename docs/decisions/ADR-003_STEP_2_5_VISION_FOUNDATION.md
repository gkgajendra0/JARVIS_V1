# ADR-003 — Step 2.5 Vision Foundation Boundaries

Date: 2026-08-29
Status: Accepted for implementation; detector/tracker implementation choice pending measured benchmark

## Context

JARVIS V1 completed Step 2 and began Step 3 research. The human owner then approved a bounded Step 2.5 interlude after proving that the available DJI Osmo Pocket 3 works as a USB webcam and that Python can physically control its pan/tilt/zoom through `duvc-ctl` on the target Windows system.

The goal is not to build full computer vision. It is to add the smallest reusable visual foundation that can later support identity evidence, semantic vision, multi-camera use, and passive awareness without locking JARVIS to one camera, detector, tracker, or cloud provider.

## Decision

Adopt the following ownership boundaries:

1. `CameraSource` is the only camera-capture boundary. It owns open/close and fresh-frame delivery.
2. Capture uses latest-frame semantics rather than an unbounded FIFO backlog.
3. `PtzController` is separate from capture even when the same physical device provides both.
4. Pocket 3 PTZ uses `duvc-ctl` behind an adapter because it is already proven on the actual hardware.
5. Detector-specific outputs are translated into JARVIS-owned `Detection` values.
6. Tracker-specific outputs are translated into JARVIS-owned `Track` values.
7. `TargetManager` is JARVIS-owned and determines the selected track. Trackers do not choose the active target.
8. `FollowController` is JARVIS-owned deterministic code. Models/trackers never issue motor commands directly.
9. Vision exposes only small canonical state required by the active slice. No generic event bus, multi-camera registry, or GPU resource manager is introduced yet.
10. Vision evidence cannot authorize actions. Step 3 remains the owner of identity/trust/authority semantics.

## Technology Status

Accepted immediately:

- OpenCV as the initial capture adapter mechanism, with MSMF vs DSHOW benchmarked on the real camera;
- `duvc-ctl` for the Pocket 3 PTZ adapter;
- provider-neutral domain contracts and JARVIS target/follow policy.

Not yet frozen:

- detector winner: RF-DETR Nano/Small vs RT-DETRv4-S;
- tracker winner: ByteTrack vs BoT-SORT + camera-motion compensation;
- capture backend: MSMF vs DSHOW;
- optimization backend: native PyTorch/CUDA first, TensorRT only if needed.

Deferred:

- Roboflow Inference server as a mandatory runtime dependency;
- face recognition/authentication;
- OCR/pose/gesture/VLM;
- visual memory and continuous recording;
- multi-camera orchestration;
- passive world awareness;
- generic vision event/resource infrastructure.

## Rationale

This preserves replacement boundaries while avoiding speculative framework code. The important future-proofing comes from canonical JARVIS semantics and narrow device/model interfaces, not from empty registries or managers created before a second real requirement exists.

A moving PTZ camera changes the tracker problem: camera motion shifts the entire frame. Therefore BoT-SORT with camera-motion compensation is a first-class benchmark candidate rather than assuming ByteTrack is sufficient.

## Consequences

Positive:

- camera, detector, tracker, and PTZ implementations can evolve independently;
- no ML library controls physical hardware directly;
- current code remains useful if detector/tracker technology changes;
- later identity evidence can consume vision state without granting vision authority;
- the Step 2.5 implementation remains small enough to test and clean up.

Costs:

- adapters add small translation overhead;
- detector/tracker selection remains open until real benchmarks run;
- the initial version intentionally omits broader visual capabilities.

## Reconsideration Triggers

Revisit this ADR if:

- a second concurrent camera is added;
- remote/distributed camera inference becomes required;
- direct Python inference cannot meet measured latency/resource gates;
- tracker continuity remains unacceptable with BoT-SORT/CMC;
- later visual consumers create a real need for an event stream or shared model resource manager.

## Acceptance

The human owner approved the Step 2.5 roadmap insertion and authorized implementation on 2026-08-29 after the research review.