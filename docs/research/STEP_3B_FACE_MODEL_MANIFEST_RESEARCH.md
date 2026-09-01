# Step 3B Face Model Manifest Research

## Status

**3B.2 MODEL MANIFEST / ASSET BOUNDARY AUTOMATED-VALIDATED AND EXERCISED BY HUMAN-ACCEPTED 3B.3 REAL OWNER-MACHINE MODEL SMOKE**

This record freezes the exact initial face-detection and face-recognition assets used for the Phase 3B benchmark path. It is intentionally narrower than a general face-recognition technology review; the Step-3 architecture already selected YuNet + SFace as the initial local benchmark pair, subject to real calibration and provenance review.

## Upstream baseline

Frozen source repository:

- OpenCV Zoo: `https://github.com/opencv/opencv_zoo`
- revision: `47534e27c9851bb1128ccc0102f1145e27f23f98`
- revision date: 2026-05-28
- revision purpose: merged the YuNet dynamic-input model for OpenCV 5.x ONNX Runtime compatibility.

JARVIS must not silently follow OpenCV Zoo `main`. Model changes require a new manifest revision, checksum review, benchmark, and explicit promotion.

## YuNet face detector

Selected asset:

- role: `face_detector`
- asset ID: `opencv-yunet-face-detector-2026may`
- filename: `face_detection_yunet_2026may.onnx`
- source path: `models/face_detection_yunet/face_detection_yunet_2026may.onnx`
- exact Git LFS object SHA-256: `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`
- exact size: `229738` bytes
- model/directory license: MIT
- intended initial backend: OpenCV 5 default CPU graph-engine path.

### Why the 2026 model replaces the old 2023 file for JARVIS

OpenCV Zoo states that `face_detection_yunet_2026may.onnx` is the default YuNet model with dynamic `height` / `width` input dimensions and is compatible with the OpenCV 5.x ONNX Runtime engine. The older `face_detection_yunet_2023mar.onnx` has fixed input dimensions and is therefore not the correct default for this project's pinned OpenCV 5.0.0.93 runtime.

The 2026 asset is a re-export of the 2023 model with the static H/W dimensions replaced by symbolic dimensions; it is not being treated as a newly trained identity model.

YuNet's upstream research/training path is publicly linked from OpenCV Zoo, and the directory has an MIT license. This is sufficiently documented for the current private local benchmark path.

## SFace recognizer

Selected asset:

- role: `face_recognizer`
- asset ID: `opencv-sface-recognizer-2021dec`
- filename: `face_recognition_sface_2021dec.onnx`
- source path: `models/face_recognition_sface/face_recognition_sface_2021dec.onnx`
- exact Git LFS object SHA-256: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
- exact size: `38696353` bytes
- OpenCV-Zoo directory license declaration: Apache-2.0
- feature shape observed on the accepted owner machine: `(1, 128)`.

OpenCV Zoo describes the model as a MobileFaceNet instance trained with SFace loss and converted from the original SFace code base.

### Provenance caveat

The OpenCV Zoo directory clearly declares Apache-2.0 licensing for its files, but the exact training-dataset provenance/rights for the distributed `face_recognition_sface_2021dec.onnx` weight are not fully documented in the public materials reviewed for this phase.

Therefore:

- private local JARVIS benchmarking may proceed;
- the model must not be represented as having fully resolved training-data provenance;
- any future commercial distribution, redistribution, hosted biometric service, or external productization must re-review the weight's provenance and applicable rights before promotion;
- this caveat is a model-governance issue, not a reason to weaken local biometric privacy/security controls.

## Thresholds

Any cosine/L2 thresholds published by upstream OpenCV/SFace demos are reference benchmark values only.

They are **not** JARVIS trust thresholds and must not be wired into authority logic.

JARVIS must calibrate its own face-match threshold using the real Pocket 3 pipeline, including:

- same-owner positives across ordinary lighting, distance, pose, glasses, and appearance variation;
- non-owner negatives;
- photo/screen/video replay conditions;
- track-association failures and reacquisition;
- explicit false-accept / false-reject measurements.

No face threshold can directly authorize an action; Phase 3A remains the authority boundary.

## Asset/cache policy

Model binaries are not committed to the JARVIS repository.

The packaged manifest pins:

- source repository revision;
- exact immutable source URL;
- exact filename;
- exact byte count;
- SHA-256;
- role/model identifier;
- license/provenance notes;
- deployment/calibration status.

The local `ModelAssetCache`:

1. uses an external cache, `%LOCALAPPDATA%/JARVIS/models` on Windows by default;
2. allows explicit `JARVIS_MODEL_CACHE` override;
3. verifies an existing cached asset by exact size and SHA-256 before use;
4. downloads to a temporary file;
5. rejects an over-size, short, or hash-mismatched download;
6. atomically replaces the target only after integrity passes;
7. never silently changes model version;
8. treats missing/tampered assets as unavailable rather than falling back to an unpinned model.

## OpenCV 5 backend note

The first real owner-machine smoke used explicit `DNN_TARGET_CPU` arguments. OpenCV 5.0 emitted:

`Targets are not supported by the new graph engine for now`

The models nevertheless loaded and inferred correctly. The diagnostic was subsequently aligned with the current OpenCV 5 path by removing the unnecessary explicit backend/target overrides and using the default graph-engine execution path.

This warning was therefore not treated as a model failure and is not part of the promoted runtime configuration.

## Real owner-machine Step 3B.3 acceptance — 2026-08-30

Environment:

- OpenCV: `5.0.0`
- model cache: `%LOCALAPPDATA%/JARVIS/models`
- OpenCV Zoo revision: `47534e27c9851bb1128ccc0102f1145e27f23f98`

Integrity:

- YuNet exact pinned SHA-256 matched;
- SFace exact pinned SHA-256 matched.

Observed first-run fetch/verify:

- YuNet: `1035.4 ms`
- SFace: `10186.7 ms`

Observed CPU smoke timing:

- YuNet load: `47.8 ms`
- YuNet synthetic inference: median `3.49 ms`, p95 `3.79 ms`, range `3.25–3.80 ms`
- SFace load: `92.9 ms`
- SFace synthetic feature: median `6.92 ms`, p95 `7.56 ms`, range `6.51–7.62 ms`
- SFace feature shape: `(1, 128)`

Privacy/non-enrollment gate:

- no camera opened;
- no OWNER profile created;
- no biometric template persisted;
- final diagnostic: `STEP_3B3_MODEL_SMOKE = PASS`.

This human run also exercised the previously automated-only 3B.2 exact-hash/cache boundary end-to-end on the owner machine. The accepted combined 3B.2/3 boundary remains limited to model integrity/cache behavior and synthetic-input runtime viability. It does not accept face-match accuracy, production thresholds, liveness, OWNER enrollment, T2 trust, or any authority use.

## Next gate

Step 3B.4 uses the real Pocket 3 in a non-persistent read-only benchmark. Identity processing must occur only on the head associated by the existing JARVIS selected-track/head-framing policy. It must not create a second full-frame identity scanner and must not persist frames or feature vectors.
