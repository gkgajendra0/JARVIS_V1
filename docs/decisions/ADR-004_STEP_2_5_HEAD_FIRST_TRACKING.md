# ADR-004 — Step 2.5 Head-First Tracking

Date: 2026-08-29
Status: Accepted for implementation from measured Pocket 3 benchmark

## Context

The first closed-loop Step 2.5 follow test proved that JARVIS can capture the Pocket 3 feed, detect a person, maintain a ByteTrack trajectory, explicitly lock and arm a target, and physically move the Pocket 3 gimbal. The same live test exposed two issues:

1. the generic RF-DETR person detector could classify a close hand/forearm as a person candidate;
2. using the full-body box as the motor anchor produced reactive/glitchy framing.

JARVIS therefore needs a stronger distinction between coarse human/body continuity and the precise visual anchor used for camera framing.

## Decision

Adopt a **head-first, body-linked fallback** architecture.

Selected head detector: **MediaPipe BlazeFace Full-Range**.

Selected production settings:

- confidence threshold: `0.65`;
- 3 consecutive linked-head frames required before a body track becomes head-confirmed;
- a head-confirmed body track may be explicitly locked;
- head observations are the primary framing anchor;
- if confirmed head evidence disappears, only the already-selected body track may be used as bounded fallback;
- a new body/person candidate is never silently substituted;
- body/face/tracker evidence remains non-authoritative for identity or permissions.

## Measured Evidence

The selection used the same 1,796-frame, 1280x720 Pocket 3 clip for OpenCV YuNet 2026May and MediaPipe BlazeFace Full-Range.

At threshold 0.50:

- YuNet mean latency 32.34 ms, p95 36.51 ms, hand-only false positives 43.81%;
- BlazeFace mean latency 5.37 ms, p95 5.79 ms, hand-only false positives 10.95%;
- both achieved 100% frontal and profile/up/down detection;
- far/near detection was 92.00% YuNet and 91.67% BlazeFace;
- fast-motion detection was 92.80% YuNet and 94.07% BlazeFace.

Threshold sweep for BlazeFace:

- `0.60`: 84.88% face coverage, 4.29% hand FP, longest hand streak 7 frames;
- `0.65`: 84.23% face coverage, 0.95% hand FP, longest hand streak 2 frames;
- `0.70`: 82.19% face coverage, 0.00% hand FP.

The 0.65 threshold plus a 3-frame confirmation gate preserves more usable face coverage than 0.70 while rejecting every observed hand-only false-positive streak in the controlled benchmark. At 30 FPS the confirmation delay is roughly 100 ms.

YuNet was not selected because hand-only false positives remained sustained even at high thresholds: at 0.80 it still produced 19.05% hand false positives with a longest streak of 17 frames (~0.57 s).

## Architecture

```text
CameraSource
    |
    +--> RF-DETR Nano -> ByteTrack body tracks
    |
    +--> MediaPipe BlazeFace Full-Range -> HeadObservation[]
                                          |
                                  HeadFirstFramingPolicy
                                          |
                                  3-frame confirmation
                                          |
                                  explicit TargetManager lock
                                          |
                              head anchor / same-body fallback
                                          |
                                    FollowController
                                          |
                                      PtzController
```

## Consequences

Positive:

- a generic hand/body false positive cannot become a follow target merely because RF-DETR called it a person;
- the camera can compose around the head rather than a full-body center;
- temporary face loss does not force target switching because RF-DETR + ByteTrack remain the coarse continuity layer;
- the provider is behind the JARVIS `HeadDetector` boundary;
- temporal validity is JARVIS-owned policy, not delegated to the model.

Costs:

- MediaPipe becomes a production vision dependency;
- current upstream dependency metadata creates an OpenCV packaging conflict: `trackers==2.6.0` requires `opencv-python`, while `mediapipe==1.0.1` requires `opencv-contrib-python`;
- JARVIS therefore pins both OpenCV distributions to the exact same `5.0.0.93` build as a temporary compatibility compromise so package metadata and `pip check` remain valid; both expose the same `cv2` namespace and this must be revisited if the versions diverge;
- Roboflow's own current inference requirements explicitly use the same dual-wheel workaround because its dependencies require both distributions;
- partial face occlusion is weaker than YuNet in the controlled clip, so the body-linked fallback remains necessary;
- head-first target selection does not solve long-gap human identity; that remains Step 3.

## Reconsideration Triggers

Revisit the detector or thresholds if:

- integrated live Pocket 3 testing shows materially different false positives from the recorded benchmark;
- room-scale profile/occlusion performance is insufficient even with same-body fallback;
- MediaPipe becomes incompatible with the target Python/OpenCV runtime;
- either `trackers` or MediaPipe relaxes its OpenCV package requirement so JARVIS can return to one OpenCV wheel;
- another permissively usable detector materially improves the measured accuracy/latency/safety tradeoff;
- Step 3 face recognition requires a different face alignment detector and consolidating the stack produces a measured advantage.

## Acceptance Boundary

This ADR accepts the technology and control semantics for implementation. Step 2.5 remains unaccepted as a whole until integrated BlazeFace live validation, hand/forearm rejection, smooth physical head-follow, target-loss behavior, multi-person no-switch behavior, and long-run resource/shutdown validation pass on the actual system.
