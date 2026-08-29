# JARVIS V1 Current Plan

## Active Step

**Step 2.5 — Vision Sensor & Active Target Tracking Foundation**

## Current Stage

**IMPLEMENTED + AUTOMATED-VALIDATED + HUMAN-ACCEPTED — FINAL MERGE GATE**

Step 2 was human-accepted on 2026-08-29. Step 3 research began immediately afterward, but the human owner explicitly approved a bounded roadmap interlude to establish JARVIS visual sensing and active target tracking before Step 3 implementation continues.

Step 2.5 is now functionally complete and human-accepted. The only remaining action is final repository quality validation and merge. After merge, development workflow improvements such as supervised auto-sync/restart may be implemented before Step 3 begins.

## Accepted Objective

JARVIS now has a reusable visual foundation that can:

- own one Pocket 3 camera capture path;
- receive fresh frames without unbounded backlog;
- detect people through a replaceable detector adapter;
- maintain stable target tracks through a replaceable tracker adapter;
- require explicit target lock and separate follow arming;
- use head-first framing with bounded body fallback;
- pan, tilt, and adaptively zoom the Pocket 3 through a replaceable PTZ adapter;
- stop/disarm safely on target expiry without silently switching people;
- expose canonical visual state to voice tools;
- display an optional live observer window using the same camera/runtime state as JARVIS.

## Frozen Architecture

```text
Pocket 3 / OpenCV DirectShow / latest-frame capture
                    |
                    +--> MediaPipe BlazeFace Full-Range --> head evidence
                    |
                    +--> RF-DETR Nano BF16 --> OC-SORT + DIoU --> person tracks
                                                       |
                                                TargetManager
                                                       |
                                           Head-first framing policy
                                                       |
                                      Follow + adaptive zoom controllers
                                                       |
                                            duvc-ctl PTZ adapter
                                                       |
                                                Pocket 3 gimbal

Canonical runtime state --> diagnostics / voice tools / optional observer window
```

## Frozen Technology Decisions

### Capture

- JARVIS-owned `CameraSource` contract.
- OpenCV DirectShow (`CAP_DSHOW`) on Windows.
- 1280x720 initial tracking mode.
- One physical camera owner.
- Latest-frame / bounded-overwrite semantics.
- Controlled Pocket 3 test sustained about 29.34 FPS over 300/300 frames.

### Person detector

- JARVIS-owned `ObjectDetector` contract.
- RF-DETR Nano.
- Native PyTorch/CUDA BF16.
- Low candidate floor retained for tracker association; raw detector candidate count is engineering telemetry and is not treated as canonical visible-person count.

### Head detector

- MediaPipe BlazeFace Full-Range through a JARVIS-owned head boundary.
- Initial lock requires three consecutive linked-head frames.
- Head evidence is framing/identity evidence only; it is not authentication.

### Tracker

- JARVIS-owned `Tracker` contract.
- Production default: Roboflow OC-SORT with DIoU association and XYXY state estimation for fast/non-linear body motion.
- Timestamp-aware updates.
- Lost-track buffering retained for short gaps.
- BoT-SORT and ByteTrack adapters remain replaceable fallbacks behind the same contract.
- Human fast sit/stand testing preserved the same track ID after the OC-SORT change.

### Target and framing policy

- `TargetManager` owns deterministic explicit target selection.
- No automatic target switching.
- Lock requires exactly one visible head-confirmed candidate in the current test surface.
- Follow requires a separate explicit arm action.
- HEAD is the primary framing anchor.
- HEAD_HOLD briefly preserves trusted head height while the same body track supplies horizontal continuity.
- BODY fallback uses the same locked body track with reduced-authority tilt.
- Target expiry clears selection and disarms follow.

### PTZ and zoom

- JARVIS-owned `PtzController` contract.
- `duvc-ctl` adapter for Pocket 3 pan, tilt, and zoom.
- Hardware ranges are queried dynamically and treated as device units, not degrees.
- Pocket 3 tilt polarity is calibrated and regression-tested.
- Direction-specific pan scaling compensates measured left/right response asymmetry.
- Adaptive zoom uses the already locked BODY track size with hysteresis and a conservative range cap; zoom never selects or changes a target.

### Observer and truthfulness

- Optional `JARVIS_VISION_PREVIEW=true` observer window shares the same camera/runtime instead of opening a second pipeline.
- Display refresh is decoupled from inference refresh so the camera view can remain smooth while showing the latest completed interpretation.
- The window exposes track boxes/IDs, head boxes, lock state, framing source, pan/tilt/zoom commands, and analysis age.
- Voice-facing state uses canonical tracked-person counts rather than raw RF-DETR candidate counts.
- Step 2.5 does not provide general scene understanding, face identity, OCR, or authorization.

## Human Acceptance Evidence

Human testing on the actual Windows + RTX 5060 Ti + DJI Pocket 3 setup confirmed:

- integrated camera capture and vision runtime start reliably;
- one visible person can be explicitly locked and separately armed;
- head-first framing operates and degrades through HEAD -> HEAD_HOLD -> BODY safely;
- pan/tilt/zoom follow works in real use;
- target loss stops/clears follow rather than silently switching targets;
- multiple-person handling does not intentionally retarget away from the locked track;
- live observer reflects the same canonical JARVIS runtime state;
- fast sit/stand body motion preserves the same OC-SORT track ID;
- final owner feedback: Step 2.5 is working well with no remaining blocking functional issue.

## Long-Run / Cleanup Status

- Tracker first-seen bookkeeping is bounded so an always-running process does not retain historical track IDs indefinitely.
- Camera shutdown uses a stop signal, bounded thread join, and capture release; no human-observed shutdown failure remains open.
- Benchmark-only alternatives remain outside the production architecture.

## Explicitly Deferred to Step 3 or Later

- face recognition / owner identity;
- liveness / anti-spoofing;
- voice identity;
- trust scoring and authorization;
- OCR;
- gesture/pose/pointing;
- local/cloud VLM scene reasoning;
- visual memory;
- proactive surveillance or continuous recording;
- multi-camera fusion/registry;
- smart glasses/HUD.

## Step-3 Boundary

Vision outputs remain evidence, never authority:

```text
vision / face / presence evidence
            |
            v
Step 3 identity + graduated trust
            |
            v
future authorization policy
```

Wake word, person tracking, head detection, and future face recognition must never grant permission directly.

## Completion Gate

Step 2.5 has satisfied implementation, automated validation, real Pocket 3 closed-loop use, and human acceptance. Final completion requires only a green final branch quality gate and merge into `main`.

## Immediate Next Actions

1. Run the final GitHub quality gate on the exact accepted branch head.
2. Merge Step 2.5 into `main`.
3. Implement the development-only supervised Git auto-sync/restart workflow.
4. Begin Step 3 Identity + Graduated Trust + Authority, with face recognition introduced as identity evidence rather than direct authentication.
