# Step 2.5 Research — Head-First Human Tracking and Auto-Framing

Date: 2026-08-29
Status: Research complete; local benchmark required before technology freeze

## Why this research was added

The first physical Step 2.5 follow loop succeeded: Pocket 3 capture, RF-DETR Nano person detection, ByteTrack, explicit lock/arm, and PTZ movement all worked end to end. Two human-acceptance findings remain:

1. a close hand/forearm could be classified by the generic person detector as a person candidate;
2. physical following worked but movement was visibly/glitchily reactive.

This research asks whether JARVIS should follow a face/head instead of a full-body box, whether there is mature technology worth adopting rather than writing from scratch, and what successful commercial auto-framing systems do differently.

## Industry evidence

### DJI Osmo Pocket 3

DJI already implements ActiveTrack 6.0, Face Auto-Detect, and Dynamic Framing on Pocket 3. DJI describes Face Auto-Detect as automatically recognizing a single-person subject and smoothly tracking them in center frame. ActiveTrack can select a subject and drive the gimbal automatically.

Official references:

- https://www.dji.com/support/product/osmo-pocket-3
- https://repair.dji.com/help/content?customId=01700009024&documentType=artical&lang=en&paperDocType=paper&re=US&spaceId=34

The official webcam documentation does not expose a supported PC API for commanding ActiveTrack or consuming its target state. Community reports indicate that onboard tracking can work in webcam mode after manual activation on the camera, but this is not a documented programmable integration contract.

Implication: DJI ActiveTrack is an excellent behavioral benchmark for smoothness, but not the initial JARVIS production controller because JARVIS would lose target/state/policy ownership and would rely on undocumented/manual activation.

### Insta360 Link series

Insta360 documents gimbal AI Tracking that recognizes and follows a person, exposes tracking speed and frame size, and explicitly states that AI Tracking is designed to track human faces rather than hands, objects, or pets. It can resume tracking when the subject leaves and reappears.

Official reference:

- https://onlinemanual.insta360.com/link/en-us/operating-tutorials/track/ai-track

Implication: face/head-first tracking is a proven commercial design for a gimbal webcam. Subject position, tracking speed, and frame size should be first-class control concepts rather than always centering an entire body box.

### Logitech RightSight 2

Logitech combines computer vision with framing policies and explicitly uses thresholds/speed controls to avoid rapid camera movement. Speaker View can combine vision with audio direction and deliberately delays reframing because rapid camera movement harms the viewing experience.

Official reference:

- https://hub.sync.logitech.com/collabosguides/post/3-4-rightsight-2-speaker-view-group-view-PXdfb8qcHkzCMwb

Implication: a good auto-framing controller should include hysteresis/dwell, smoothing, and configurable framing speed. Reacting to every frame is not the target behavior.

### Microsoft Windows Studio Effects and NVIDIA Broadcast

Both implement automatic framing as a mature product feature. Microsoft describes Automatic Framing as detecting a person and cropping/zooming to keep them framed; NVIDIA Broadcast tracks user movement and dynamically crops/zooms to keep the user centered.

References:

- https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/studio-effects
- https://www.nvidia.com/en-in/design-visualization/software/broadcast-app/

These are useful behavioral references, but they do digital framing rather than exposing the JARVIS-owned physical Pocket 3 PTZ/identity contract we need.

## Open technology candidates

### Candidate A — OpenCV YuNet face detector

Current OpenCV Zoo default: `face_detection_yunet_2026may.onnx`.

Important properties:

- lightweight face detector;
- official OpenCV integration (`FaceDetectorYN` / OpenCV DNN);
- current 2026 model supports dynamic input sizes with OpenCV 5.x;
- model file is approximately 230 KB;
- returns a face box plus five facial landmarks, which is enough for a stable head/face anchor and later SFace alignment;
- WIDER Face validation reported by OpenCV Zoo: Easy AP 0.8844, Medium AP 0.8656, Hard AP 0.7503 for the standard model;
- model directory is MIT licensed;
- JARVIS already depends on OpenCV 5.0, so this adds a model asset but no new inference framework.

Official references:

- https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE

Research status: **PRIMARY BENCHMARK CANDIDATE**.

Why: smallest dependency delta, permissive model license, five landmarks are enough for framing, and it fits the existing OpenCV capture/runtime boundary.

### Candidate B — MediaPipe Face Detector

Current MediaPipe Tasks provides image/video/live-stream face detection. Live-stream inference is asynchronous and may drop input frames to reduce latency rather than build a stale queue, which matches JARVIS latest-frame semantics. It has configurable confidence and NMS thresholds.

MediaPipe itself is Apache-2.0 and current Python packaging supports Windows/Python 3.11.

Official references:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceDetector
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceDetectorOptions
- https://github.com/google-ai-edge/mediapipe

Research status: **PRIMARY BENCHMARK CANDIDATE**.

Why: mature on-device streaming design and naturally handles latest-result semantics. Cost: adds another vision runtime/dependency when OpenCV is already present.

### Candidate C — MediaPipe Face Landmarker

Provides dense face landmarks, face-presence confidence, tracking confidence, optional facial transformation matrices, and live-stream mode.

Official reference:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions

Research status: **DEFER AS DEFAULT; BENCHMARK ONLY IF NEEDED**.

Why: excellent if JARVIS later needs head pose, gaze/face geometry, expression features, or more stable geometric anchors. For basic PTZ framing, hundreds of landmarks are unnecessary compared with a face detector returning five landmarks.

### Candidate D — MediaPipe Pose Landmarker

Provides 33 pose landmarks, visibility/presence information, world landmarks, tracking confidence, and live-stream processing. This is useful when the face is turned away or temporarily unavailable while the body remains visible.

Official references:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarkerOptions
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarkerResult

Research status: **SECONDARY FALLBACK CANDIDATE, NOT PRIMARY FOLLOW TARGET**.

Why: useful for robust human validation and shoulder/head estimation when no face is visible. It should not replace a dedicated face/head anchor for normal framing.

### Candidate E — MediaPipe Holistic Landmarker

The current Holistic Landmarker can return face, pose, left-hand, and right-hand landmarks, optionally with segmentation. It is attractive because it semantically separates hands from the human pose.

Official references:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HolisticLandmarker
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HolisticLandmarkerResult

Research status: **DEFER / OVERKILL FOR STEP 2.5**.

Why: it solves more problems than current follow mode requires and would couple face/pose/hand processing into every frame. Reconsider later for gestures or whole-body interaction.

### Future identity candidate — OpenCV SFace

OpenCV Zoo provides SFace face recognition, designed to pair with YuNet's five face landmarks. OpenCV reports 0.9940 accuracy in its published evaluation table, and the SFace model directory is Apache-2.0 licensed.

Official reference:

- https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface

Research status: **PROMISING FOR STEP 3 IDENTITY BENCHMARK, NOT STEP 2.5 AUTHORIZATION**.

Why this matters: it gives JARVIS a permissively licensed local face-recognition candidate for later mapping ephemeral visual tracks to owner identity, without pretending tracker IDs are identity.

## Recommended architecture

Do not use a single detector output as both "human exists" and "where the camera should point".

Recommended model:

```text
CameraSource
    |
    +--> Face/Head Detector ------------------------+
    |       |                                       |
    |       +--> HeadTrack[]                        |
    |               |                               |
    |               +--> PRIMARY framing anchor     |
    |                                               |
    +--> RF-DETR Nano person detector               |
            |                                       |
            +--> ByteTrack body tracks              |
                    |                               |
                    +--> linked body continuity -----+
                                    |
                                    v
                             TargetManager
                                    |
                             FramingTarget
                                    |
                     temporal smoothing/hysteresis
                                    |
                            FollowController
                                    |
                       rate/slew-limited PTZ intent
                                    |
                            PtzController
```

### Primary anchor

When the selected person's face/head is visible, control the gimbal from the head/face anchor, not the whole-body center.

The desired composition point should be configurable. A natural portrait framing point is slightly above image center rather than forcing the face to exactly `(0.5, 0.5)`, leaving appropriate headroom and body context.

### Body-linked fallback

RF-DETR Nano and ByteTrack remain valuable. They should become the coarse person/continuity layer rather than the normal motor anchor.

When a face is visible inside a person track, link the head track to that body track. If the face disappears briefly because of profile, occlusion, blur, or the person turning away:

1. retain the same selected target identity/track relationship for a bounded interval;
2. use the already-linked body track only for continuity/reacquisition;
3. if physical movement is allowed during fallback, make it slower/more conservative than face-driven movement;
4. never select a new body/person candidate merely because the face disappeared;
5. if the linked target expires, disarm and stop.

This prevents a standalone hand false positive from becoming the framing anchor.

### Tracking

Keep ByteTrack as the current generic continuity layer where it is useful. A face detector itself does not equal persistent identity. If multiple faces are present, JARVIS still needs explicit target ownership.

Do not make a face-track ID persistent across room exits. Long-gap re-identification belongs to Step 3 identity evidence, where a face embedding/recognizer such as SFace can be benchmarked and governed separately.

## Motion-control recommendation

The first physical loop proved that frame-by-frame proportional corrections feel too reactive. Commercial systems confirm that smooth framing intentionally avoids immediate response to every small motion.

Add the following JARVIS-owned control semantics before human acceptance:

1. **filtered target anchor** — smooth head-center observations before control;
2. **dead zone + hysteresis** — enter movement only after crossing a larger threshold and stop only after returning to a smaller inner threshold;
3. **dwell/debounce** — require an offset to persist briefly before moving;
4. **slew/acceleration limit** — bound how quickly PTZ command magnitude changes;
5. **command cadence** — keep PTZ commands at a measured lower frequency than perception;
6. **composition point** — target a configurable portrait anchor, not exact box center;
7. **fallback speed reduction** — body-only fallback moves slower than face/head-confirmed tracking;
8. **loss behavior** — no visible selected target means no new motor command; expiry disarms.

PID should still not be added automatically. First test filtered proportional control with hysteresis/slew limiting. Add integral/derivative terms only if measured steady-state or oscillation behavior requires them.

## What not to adopt as the JARVIS core

### DJI onboard ActiveTrack as the only controller

Useful benchmark and optional manual mode, but not selected as JARVIS core because there is no documented PC API exposing programmable target selection/state/identity integration in webcam mode. JARVIS would surrender policy/state ownership.

### Windows Studio Effects / NVIDIA Broadcast

Excellent auto-framing products, but their primary operation is digital crop/zoom and they do not provide the physical Pocket 3 target/PTZ ownership boundary required by JARVIS.

### InsightFace pretrained models

Technically strong, but pretrained-model licensing has restrictions that are less clean than the permissive OpenCV YuNet + SFace path. Do not make it the default without a separate licensing review.

### Face-only with no fallback

Rejected as the final architecture. Face-only tracking fails naturally when the person turns away, is occluded, blurred, too distant, or leaves the face partially outside the frame. Head-first plus linked body continuity is more robust while still preventing body-part false positives from becoming motor targets.

## Benchmark required before freeze

Use the same research discipline as the detector/tracker selection. Benchmark on actual Pocket 3 footage and hardware before selecting a face/head provider.

Candidate benchmark set:

1. OpenCV YuNet 2026May;
2. MediaPipe Face Detector;
3. optionally MediaPipe Face Landmarker only if basic face detectors are insufficient.

Test scenarios:

- frontal face near/medium/far;
- glasses;
- profile left/right;
- looking down/up;
- partial face;
- hand covering part of face;
- hand/forearm alone close to camera (must not become a face);
- face leaves and returns;
- quick lateral movement;
- blur during movement;
- second real person enters;
- camera pan while face remains visible;
- back-of-head / face unavailable to validate body-linked fallback.

Measure:

- face coverage while a usable face is visible;
- false-positive rate on hands/objects/background;
- reacquisition time;
- head-center jitter frame to frame;
- inference mean/median/p95 latency;
- CPU/GPU/VRAM impact;
- multi-face separation;
- behavior under skipped frames;
- ease of mapping output into JARVIS canonical types.

## Provisional recommendation

**Benchmark OpenCV YuNet first against MediaPipe Face Detector.**

If YuNet matches MediaPipe on the local Pocket 3 scenarios, select YuNet because it is tiny, permissively licensed, uses the OpenCV runtime already in JARVIS, provides five landmarks, and adds the least complexity.

If MediaPipe materially wins on profile/partial-face continuity or asynchronous live-stream latency, select MediaPipe Face Detector despite the extra dependency.

Do not add Face Landmarker, Pose Landmarker, or Holistic to the production path unless the benchmark exposes a specific gap that they solve.

Regardless of face provider, keep RF-DETR Nano + ByteTrack as a linked body continuity/reacquisition layer and change motor framing to head-first control with smoothing/hysteresis/slew limits.
