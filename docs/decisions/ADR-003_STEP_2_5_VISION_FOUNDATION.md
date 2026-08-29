# ADR-003 — Step 2.5 Vision Foundation Boundaries

Date: 2026-08-29
Status: Accepted for implementation; capture backend and detector selected; tracker choice pending measured benchmark

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

- OpenCV as the initial capture adapter mechanism;
- DirectShow (`CAP_DSHOW`) as the initial Pocket 3 Windows capture backend;
- 1280x720 as the initial low-latency tracking mode;
- `duvc-ctl` for the Pocket 3 PTZ adapter;
- RF-DETR Nano as the initial detector;
- BF16 native PyTorch/CUDA as the initial RF-DETR inference mode;
- provider-neutral domain contracts and JARVIS target/follow policy.

The capture choice is based on the actual Windows + Pocket 3 benchmark:

- MSMF 1280x720: 5/5 open/read success, ~2.96 s average open-to-first-frame;
- MSMF 1920x1080: 4/5 successful first reads with one grab failure, ~4.834 s average;
- DSHOW 1280x720: 5/5 success, ~0.968 s average open-to-first-frame;
- DSHOW 1920x1080: 5/5 success, ~0.847 s average open-to-first-frame;
- DSHOW 1280x720 sustained run: 300/300 successful frames in 10.226 s, ~29.34 effective FPS.

DSHOW FPS metadata returned `-1`, so JARVIS must rely on measured frame timing rather than treating backend FPS metadata as authoritative. 1080p remains supported as a configurable candidate but is not the default until sustained processing evidence justifies it.

The detector choice is based on the actual Windows + RTX 5060 Ti + Pocket 3 benchmarks.

Performance results:

- RF-DETR Nano BF16: 36.97 ms mean latency, 41.96 ms p95, 27.05 FPS, 114.8 MiB peak allocated VRAM;
- RF-DETR Small BF16: 40.67 ms mean latency, 45.47 ms p95, 24.59 FPS, 129.3 MiB peak allocated VRAM in the isolated live benchmark;
- RT-DETRv4-S BF16: 56.97 ms mean latency, 65.29 ms p95, 17.55 FPS, 133.2 MiB peak allocated VRAM, plus an upstream cached positional-embedding device-placement workaround in the tested native PyTorch path.

Controlled quality results used the same 900-frame, 1280x720 Pocket 3 clip for RF-DETR Nano and Small:

- Nano person coverage at confidence 0.25: 100%; at 0.50: 100%; longest miss streak: 0 frames;
- Small person coverage at confidence 0.25: 100%; at 0.50: 100%; longest miss streak: 0 frames;
- Nano vs Small disagreement frames at confidence 0.50: 0;
- Nano mean/median positive person confidence: 0.9514 / 0.9570;
- Small mean/median positive person confidence: 0.9601 / 0.9648.

Small therefore showed no continuity/coverage advantage on the controlled clip. Its confidence increase was small and did not justify its lower throughput and higher measured resource use. RF-DETR Nano BF16 is selected as the initial detector.

Not yet frozen:

- tracker winner: ByteTrack vs BoT-SORT + camera-motion compensation.

Deferred:

- TensorRT optimization unless later end-to-end measurements justify the added complexity;
- Roboflow Inference server as a mandatory runtime dependency;
- RT-DETRv4-S for the initial detector path;
- RF-DETR Small for the initial detector path;
- face recognition/authentication;
- OCR/pose/gesture/VLM;
- visual memory and continuous recording;
- multi-camera orchestration;
- passive world awareness;
- generic vision event/resource infrastructure.

## Rationale

This preserves replacement boundaries while avoiding speculative framework code. The important future-proofing comes from canonical JARVIS semantics and narrow device/model interfaces, not from empty registries or managers created before a second real requirement exists.

Although Microsoft classifies DirectShow as legacy, backend age is hidden inside the adapter and the actual Pocket 3 evidence materially favors DirectShow today. This does not make DirectShow a JARVIS domain concept; the backend remains configurable and replaceable.

RF-DETR Nano is selected because it matched RF-DETR Small on controlled person-detection continuity across the exact same 900 frames while providing better measured latency/throughput and lower resource use. RT-DETRv4-S was materially slower on the target machine and required an upstream inference workaround, so it does not justify the additional integration friction for this slice.

A moving PTZ camera changes the tracker problem: camera motion shifts the entire frame. Therefore BoT-SORT with camera-motion compensation is a first-class benchmark candidate rather than assuming ByteTrack is sufficient.

## Consequences

Positive:

- camera, detector, tracker, and PTZ implementations can evolve independently;
- no ML library controls physical hardware directly;
- current code remains useful if detector/tracker technology changes;
- later identity evidence can consume vision state without granting vision authority;
- the Step 2.5 implementation remains small enough to test and clean up;
- capture freshness is protected by one overwrite/latest-frame slot rather than a growing queue;
- the initial detector now has measured performance and quality evidence on the real target hardware.

Costs:

- adapters add small translation overhead;
- tracker selection remains open until real benchmarks run;
- the initial version intentionally omits broader visual capabilities;
- the initial Pocket 3 Windows path relies on a legacy Windows capture backend because that backend currently performs better on the real device;
- RF-DETR introduces a model/runtime dependency that must remain behind the JARVIS detector adapter.

## Reconsideration Triggers

Revisit this ADR if:

- a second concurrent camera is added;
- another Windows/backend path equals or exceeds DSHOW reliability/latency on the actual hardware;
- another detector materially exceeds Nano on controlled person-detection quality or end-to-end resource efficiency;
- remote/distributed camera inference becomes required;
- direct Python inference cannot meet measured latency/resource gates;
- tracker continuity remains unacceptable with BoT-SORT/CMC;
- later visual consumers create a real need for an event stream or shared model resource manager.

## Acceptance

The human owner approved the Step 2.5 roadmap insertion and authorized implementation on 2026-08-29 after the research review. The OpenCV/DSHOW capture choice was subsequently accepted from measured local Pocket 3 evidence on the same date. RF-DETR Nano BF16 was subsequently selected from measured local detector performance plus the controlled same-clip Nano-vs-Small quality comparison on the same date.
