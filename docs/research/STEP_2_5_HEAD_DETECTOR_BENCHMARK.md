# Step 2.5 Benchmark — Head Detector Selection

Date: 2026-08-29
Status: Complete; MediaPipe BlazeFace Full-Range selected

## Goal

Select the head/face detector used by the JARVIS head-first framing path on the actual Pocket 3 + Windows system. The detector must be fast enough to run alongside RF-DETR Nano, reject hand/forearm false positives far better than the generic person detector, and preserve useful face coverage across normal room-scale motion.

## Test Setup

Hardware/runtime:

- DJI Osmo Pocket 3 webcam input;
- 1280x720 at ~30 FPS;
- controlled 59.87-second MP4;
- 1,796 identical frames processed by each detector;
- confidence threshold 0.50 for the initial comparison;
- isolated Python 3.11 benchmark environment.

Scenarios:

- frontal face;
- profile / look up / look down;
- move farther away and return;
- partial face occlusion;
- hand/forearm only near camera;
- leave and return;
- faster lateral motion.

Candidates:

1. OpenCV YuNet `face_detection_yunet_2026may.onnx`;
2. MediaPipe Face Detector with `blaze_face_full_range.tflite`.

## Initial Same-Clip Results at Threshold 0.50

| Metric | YuNet 2026May | BlazeFace Full-Range |
| --- | ---: | ---: |
| Mean latency | 32.34 ms | 5.37 ms |
| Median latency | 31.72 ms | 5.32 ms |
| P95 latency | 36.51 ms | 5.79 ms |
| Effective detector FPS | 30.92 | 186.16 |
| CPU equivalent | 744% | 216% |
| Frontal center jitter | 0.001107 | 0.001400 |
| Frontal detection | 100.00% | 100.00% |
| Profile/up/down detection | 100.00% | 100.00% |
| Far/near detection | 92.00% | 91.67% |
| Partial occlusion detection | 48.75% | 37.92% |
| Hand-only false-positive rate | 43.81% | 10.95% |
| Leave/return detection | 87.14% | 25.71% |
| Fast-motion detection | 92.80% | 94.07% |

The overall positive-frame percentage is not used as the selection metric because the clip intentionally contains a hand-only section where a positive face detection is undesirable.

## Threshold Sweep

### YuNet

| Threshold | Face coverage | Hand FP | Longest hand-FP streak |
| --- | ---: | ---: | ---: |
| 0.50 | 88.08% | 43.81% | 87 frames / 2.90 s |
| 0.55 | 85.68% | 41.43% | 82 / 2.73 s |
| 0.60 | 83.21% | 38.57% | 55 / 1.83 s |
| 0.65 | 81.69% | 34.29% | 45 / 1.50 s |
| 0.70 | 80.45% | 30.00% | 39 / 1.30 s |
| 0.75 | 79.87% | 26.67% | 38 / 1.27 s |
| 0.80 | 79.14% | 19.05% | 17 / 0.57 s |

YuNet remained too permissive on the hand-only segment even at high thresholds. A threshold-only fix would substantially reduce usable face coverage while leaving significant sustained hand false positives.

### BlazeFace Full-Range

| Threshold | Face coverage | Hand FP | Longest hand-FP streak |
| --- | ---: | ---: | ---: |
| 0.50 | 86.34% | 10.95% | 7 frames / 0.23 s |
| 0.55 | 85.61% | 5.24% | 7 / 0.23 s |
| 0.60 | 84.88% | 4.29% | 7 / 0.23 s |
| 0.65 | 84.23% | 0.95% | 2 / 0.07 s |
| 0.70 | 82.19% | 0.00% | 0 |
| 0.75 | 79.94% | 0.00% | 0 |
| 0.80 | 78.12% | 0.00% | 0 |

## Decision

Select **MediaPipe BlazeFace Full-Range** as the initial production head detector.

Production threshold: **0.65**.

Add a JARVIS-owned temporal confirmation gate requiring **3 consecutive linked-head frames** before a body track is eligible for explicit target lock or head-driven framing.

Rationale:

- at 0.65 BlazeFace retains 84.23% aggregate face coverage across the controlled face segments;
- hand-only false positives fall to 0.95%;
- the longest observed hand false-positive streak is only 2 frames (~0.07 s);
- a 3-frame confirmation gate therefore rejects every observed hand-only false-positive streak in the benchmark while adding only ~0.10 s of confirmation delay at 30 FPS;
- threshold 0.70 would also eliminate the measured hand false positives but would reduce face coverage to 82.19%;
- BlazeFace is ~6x faster than YuNet in mean latency on the same recorded workload and used substantially less CPU in the benchmark process.

## Production Semantics

The detector does not own identity or target selection.

```text
RF-DETR person -> ByteTrack body track
                         +
                BlazeFace head evidence
                         |
                head linked to body
                         |
             3-frame confirmation gate
                         |
                 explicit target lock
                         |
          head-first framing / same-body fallback
```

Rules:

- a standalone face/head observation cannot select a target;
- a generic body/person candidate cannot be locked when head-required mode is enabled until it has 3 consecutive linked head observations;
- transient one/two-frame head detections cannot drive head framing;
- after lock, temporary loss of confirmed head evidence falls back only to the already selected body track;
- a new person/body track is never silently substituted;
- track ID remains temporary trajectory state, not human identity;
- identity/re-identification remains Step 3.

## Remaining Work

Before Step 2.5 human acceptance:

- validate BlazeFace in the real integrated camera loop;
- validate the 3-frame gate against the original hand/forearm scenario;
- validate head-first physical PTZ behavior;
- tune motion smoothing/hysteresis/slew limiting because the first body-follow test was visibly reactive;
- validate target loss and second-person no-switch behavior;
- complete integrated resource/startup/shutdown/disconnect stability tests.
