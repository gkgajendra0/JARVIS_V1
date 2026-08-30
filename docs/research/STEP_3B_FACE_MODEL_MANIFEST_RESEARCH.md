# Step 3B Face Model Manifest and Asset Research

**Status:** RESEARCH COMPLETE — 3B.2 MANIFEST/ASSET POLICY FROZEN — PROVIDER BENCHMARK NOT YET ACCEPTED  
**Date:** 2026-08-30

## Purpose

Freeze the exact face-model artifacts, provenance/licensing record, cache policy, and benchmark baseline before JARVIS captures or persists a real OWNER face template.

This is intentionally separate from provider acceptance. A model being downloadable and runnable does not make it trusted identity evidence.

## Reviewed upstream baseline

Authoritative model source reviewed:

- repository: `opencv/opencv_zoo`;
- pinned revision: `47534e27c9851bb1128ccc0102f1145e27f23f98`;
- revision message: `add Face detection model with dynamic input for OpenCV 5.x ORT engine`;
- JARVIS OpenCV runtime: `opencv-python==5.0.0.93` and `opencv-contrib-python==5.0.0.93`.

The exact artifacts are recorded in:

- `src/jarvis/identity/manifests/step3_face_models.json`.

## YuNet decision

### Selected benchmark artifact

- role: face detector;
- file: `face_detection_yunet_2026may.onnx`;
- Git LFS SHA-256: `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`;
- size: `229,738` bytes;
- directory/model license: MIT;
- upstream training path: YuNet face training on WIDER Face is documented by `ShiqiYu/libfacedetection.train`.

### Why 2026may instead of 2023mar

OpenCV Zoo now declares `face_detection_yunet_2026may.onnx` the default dynamic-input model for OpenCV 5.x ONNX Runtime. It is a dynamic-input re-export of the 2023mar model and allows variable input shapes without the older fixed-H/W limitation.

Because JARVIS is already pinned to OpenCV 5.0.0.93, the 2026may artifact is the correct current benchmark candidate. The older 2023mar file remains historical/reference material only unless a benchmark exposes a regression.

## SFace decision

### Selected benchmark artifact

- role: face recognizer/embedding provider;
- file: `face_recognition_sface_2021dec.onnx`;
- Git LFS SHA-256: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`;
- size: `38,696,353` bytes;
- OpenCV Zoo directory declaration: Apache-2.0;
- upstream description: MobileFaceNet instance trained with SFace loss and converted to ONNX.

### Provenance caveat

The exact training dataset used for this exact ONNX weight is not mapped in the OpenCV Zoo model record. The SFace paper evaluates models trained on CASIA-WebFace, VGGFace2, and MS1MV2/MS-Celeb-derived data, but that does not prove which dataset produced this exact OpenCV weight.

OpenCV Zoo issue `#313`, opened 2026-07-22, explicitly asks maintainers to clarify the commercial-use and training-data provenance of this exact ONNX checksum. It remained open during this review.

Therefore JARVIS records:

- model-license declaration: Apache-2.0 at the OpenCV Zoo directory level;
- exact-weight training provenance: **unresolved**;
- current use: acceptable as a personal-development benchmark candidate;
- commercial distribution/use: **must be re-reviewed before any commercial distribution or deployment claim**.

This avoids silently converting an upstream directory license statement into a claim about unknown training-data rights.

## Threshold policy

The upstream SFace demo uses reference same-identity thresholds:

- cosine similarity `>= 0.363`;
- normalized L2 distance `<= 1.128`.

JARVIS does **not** adopt either value as an authority threshold.

They are benchmark reference points only. The final JARVIS face threshold must be versioned from the real Pocket 3 calibration set, including owner positives, available non-owner negatives, pose/lighting/glasses/distance variation, and temporal aggregation behavior.

No vendor/demo threshold can directly create T2.

## Asset/cache policy

Model binaries are not committed to the JARVIS repository.

JARVIS packages only the immutable manifest and uses an external local cache:

- Windows default: `%LOCALAPPDATA%/JARVIS/models`;
- explicit override: `JARVIS_MODEL_CACHE`;
- non-Windows CI fallback: XDG cache or `~/.cache/jarvis/models`.

Every asset is bound by:

- exact upstream repository revision;
- exact filename/source path;
- expected byte count;
- exact SHA-256;
- code/model license record;
- provenance status;
- deployment status;
- minimum OpenCV version;
- calibration status.

`ModelAssetCache` behavior:

- never trusts an existing file without size + SHA-256 verification;
- downloads to a temporary file in the same cache directory;
- rejects over-size, under-size, or hash-mismatched downloads;
- atomically replaces the cache path only after verification succeeds;
- does not auto-upgrade to a new model/version;
- leaves a previously invalid cache file untouched if a replacement download itself fails verification.

A model-integrity failure means identity evidence is unavailable; it must not degrade into an unverified model or a weaker authority path.

## Benchmark execution policy

Initial provider benchmark will use the current mature OpenCV APIs:

- YuNet through `cv.FaceDetectorYN`;
- SFace through `cv.FaceRecognizerSF`;
- CPU first to avoid contention with the accepted RF-DETR CUDA path;
- selected/head crop from the existing vision track rather than a second independent full-frame identity pipeline.

GPU/OpenCV-DNN acceleration is considered only if the CPU benchmark cannot meet the accepted latency budget without harming camera/voice runtime.

## Next acceptance gates

3B.2 is complete when:

1. packaged manifest loads and validates in installed/editable environments;
2. exact YuNet/SFace checksum records are locked;
3. cache tampering/download mismatch tests fail closed;
4. licensing/provenance caveats are explicit;
5. model binaries remain outside Git;
6. CI remains green.

After that, 3B.3 may fetch the two pinned models on the real machine and run a non-enrollment smoke/latency benchmark. Real OWNER enrollment still waits until the provider benchmark and enrollment quality gates are defined and passed.
