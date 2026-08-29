# ADR-003 — Step 2.5 Vision Foundation Boundaries

Date: 2026-08-29
Status: Accepted for implementation; capture, detector, tracker, and inference runtime selected from measured benchmarks

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

## Selected Technology

- Capture adapter: OpenCV.
- Pocket 3 Windows capture backend: DirectShow (`CAP_DSHOW`).
- Initial tracking resolution: 1280x720.
- PTZ adapter transport: `duvc-ctl`.
- Detector: RF-DETR Nano.
- Detector runtime mode: native PyTorch/CUDA BF16.
- Tracker: Roboflow `trackers` ByteTrack.
- Target selection: JARVIS-owned `TargetManager`.
- Follow policy: JARVIS-owned bounded proportional/dead-zone `FollowController`.

## Measured Evidence

### Capture

Actual Windows + Pocket 3 results:

- MSMF 1280x720: 5/5 open/read success, ~2.96 s average open-to-first-frame;
- MSMF 1920x1080: 4/5 successful first reads with one grab failure, ~4.834 s average;
- DSHOW 1280x720: 5/5 success, ~0.968 s average open-to-first-frame;
- DSHOW 1920x1080: 5/5 success, ~0.847 s average open-to-first-frame;
- DSHOW 1280x720 sustained: 300/300 frames in 10.226 s, ~29.34 effective FPS.

DSHOW FPS metadata returned `-1`, so JARVIS must rely on measured timestamps rather than backend FPS metadata. 1080p remains configurable, but 1280x720 is the initial low-latency default.

### Detector

Actual Windows + RTX 5060 Ti + Pocket 3 results:

- RF-DETR Nano BF16: 36.97 ms mean, 41.96 ms p95, 27.05 FPS, 114.8 MiB peak allocated VRAM;
- RF-DETR Small BF16: 40.67 ms mean, 45.47 ms p95, 24.59 FPS, 129.3 MiB peak allocated VRAM in the isolated live benchmark;
- RT-DETRv4-S BF16: 56.97 ms mean, 65.29 ms p95, 17.55 FPS, 133.2 MiB peak allocated VRAM, plus an upstream cached positional-embedding device-placement workaround.

Controlled Nano-vs-Small quality comparison used the exact same 900-frame, 1280x720 Pocket 3 clip:

- Nano person coverage at confidence 0.25 and 0.50: 100%;
- Small person coverage at confidence 0.25 and 0.50: 100%;
- longest miss streak for both at both thresholds: 0 frames;
- Nano-vs-Small disagreement frames at confidence 0.50: 0;
- Nano mean/median positive person confidence: 0.9514 / 0.9570;
- Small mean/median positive person confidence: 0.9601 / 0.9648.

Small showed no continuity/coverage advantage, so its small confidence increase did not justify lower throughput and higher measured resource use. RF-DETR Nano BF16 is selected.

### Tracker

Roboflow `trackers` 2.6.0 was benchmarked using the exact same cached RF-DETR Nano person detections for both trackers. The recorded clip contained camera movement and was evaluated at both full-rate and skipped-frame stress rate.

Full rate (~30 FPS), 900 processed frames:

- ByteTrack: 99.89% confirmed-track coverage, 0 primary ID switches, 899-frame continuous primary ID run, ~0.345 ms mean / 0.479 ms p95 tracker latency;
- BoT-SORT + sparseOptFlow CMC: 99.89% coverage, 0 primary ID switches, 899-frame continuous primary ID run, ~8.843 ms mean / 9.597 ms p95 tracker latency.

Stress rate (~15 FPS), 450 processed frames with original timestamps:

- ByteTrack: 99.78% confirmed-track coverage, 0 primary ID switches, 449-frame continuous primary ID run, ~0.366 ms mean / 0.493 ms p95 tracker latency;
- BoT-SORT + sparseOptFlow CMC: 99.78% coverage, 0 primary ID switches, 449-frame continuous primary ID run, ~8.908 ms mean / 9.663 ms p95 tracker latency.

BoT-SORT + CMC produced no measurable continuity benefit on the controlled target workload while adding roughly 8.5 ms/frame of tracker overhead. ByteTrack is therefore selected for the initial tracker.

## Deferred / Not Selected

- TensorRT optimization: defer unless integrated end-to-end measurements justify the added complexity.
- Roboflow Inference server: defer; direct local integration is simpler for the current one-camera slice.
- RF-DETR Small: not selected initially; reconsider only if future difficult-scene evidence materially changes the quality tradeoff.
- RT-DETRv4-S: not selected for the initial path due slower measured performance and integration friction.
- BoT-SORT + CMC: not selected initially; reconsider if future camera motion or multi-person scenarios expose ByteTrack continuity failures.
- YOLO26: reject as default because the standard Ultralytics licensing path is unnecessarily restrictive when strong permissive alternatives meet the need.
- face recognition/authentication, OCR, pose/gesture/VLM, visual memory, continuous recording, multi-camera orchestration, passive world awareness, and generic event/resource infrastructure remain out of Step 2.5.

## Rationale

This preserves replacement boundaries while avoiding speculative framework code. Future-proofing comes from canonical JARVIS semantics and narrow device/model interfaces, not empty managers created before a second requirement exists.

Although DirectShow is legacy, it materially outperformed MSMF on the actual Pocket 3 and remains hidden behind the capture adapter.

RF-DETR Nano matched Small on controlled person continuity while being faster and lighter. RT-DETRv4-S was materially slower and needed a native-PyTorch workaround.

ByteTrack matched BoT-SORT+CMC on measured ID continuity at both full and skipped-frame rates while being about 25x cheaper in tracker-only latency. CMC therefore did not earn its complexity on the current workload.

## Consequences

Positive:

- capture, detector, tracker, target policy, and PTZ can evolve independently;
- no ML library commands physical hardware directly;
- the selected initial stack has real hardware evidence rather than benchmark-by-reputation;
- latest-frame capture plus timestamp-aware tracking avoids stale backlog assumptions;
- later identity evidence can consume visual state without granting vision authority.

Costs:

- RF-DETR/PyTorch and `trackers` become production dependencies once their adapters are implemented;
- the initial Pocket 3 path uses a legacy Windows capture backend because it performs better on the real device;
- ByteTrack may need reevaluation if future multi-person occlusion or stronger camera motion produces ID fragmentation.

## Reconsideration Triggers

Revisit this ADR if:

- a second concurrent camera is added;
- another Windows backend equals or exceeds DSHOW on the actual hardware;
- another detector materially exceeds Nano on controlled quality or end-to-end efficiency;
- ByteTrack shows unacceptable ID switches/fragmentation in real target-follow use;
- remote/distributed camera inference becomes required;
- direct Python inference cannot meet integrated latency/resource gates;
- later consumers create a real need for a shared event stream or model resource manager.

## Acceptance

The human owner approved the Step 2.5 roadmap insertion and authorized implementation on 2026-08-29. OpenCV/DSHOW, RF-DETR Nano BF16, and ByteTrack were subsequently selected from measured local evidence on the actual target hardware and controlled recorded footage on the same date. Step 2.5 itself is not yet human-accepted: integrated detector/tracker/PTZ implementation, automated validation, recovery testing, and real closed-loop target-follow acceptance still remain.
