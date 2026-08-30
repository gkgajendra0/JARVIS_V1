# Step 3B.7B — Passive RGB Presentation-Attack Detection Research

Date: 2026-08-30

## Status

**RESEARCH COMPLETE FOR BENCHMARK IMPLEMENTATION — REAL POCKET-3 BENCHMARK IN PROGRESS — NOT YET AN AUTHORITY PROVIDER**

This record follows the accepted 3B.7A randomized active-challenge primitive. The active challenge remains a valid fallback, but it is not the intended normal JARVIS experience. Normal presence verification should be passive whenever the available evidence is strong enough.

## Goal

Evaluate mature passive RGB face presentation-attack detection (PAD) technology on the real DJI Pocket 3 before any passive model is allowed to create `FACE_LIVENESS` evidence.

The benchmark must distinguish score distributions for at least:

- a live face;
- a face displayed as a static photo on a phone;
- a prerecorded face video replayed on a phone;
- a printed face photo when available.

No raw frame, face crop, PAD input tensor, or model output vector is persisted.

## Security boundary

Passive RGB PAD is supporting biometric evidence, not permission and not a strong authenticator.

A model prediction of `real` must never directly grant T2 or authorize an action. The eventual runtime must combine fresh PAD evidence with the same stable OWNER track, fresh OWNER face-match evidence, expected Windows session state, ambiguity checks, and other accepted evidence. Critical actions still require T3 through Windows Hello/FIDO2.

RGB PAD also remains fundamentally weaker than future depth/IR sensing. The provider boundary must therefore remain replaceable so a later depth/IR camera can contribute stronger evidence without redesigning authority.

## Candidate A — OpenVINO anti-spoof-mn3

Upstream: OpenVINO Open Model Zoo.

Frozen research revision: `4d4266fbbb7eb5ab80944c2800d7f304868d573d`.

Model source record:

- model: `anti-spoof-mn3.onnx`;
- size: 12,270,179 bytes;
- upstream checksum: SHA-384 `6de4534964b723397b3e8c995cadcf43bc007cc2f9930b95ae25f76adccece5d1d4d058d0b15117b9e4a9f758424f92a`;
- source: OpenVINO model storage path from the frozen Open Model Zoo manifest;
- architecture: MobileNetV3 binary classifier;
- training dataset documented by upstream: CelebA-Spoof;
- input: RGB 128x128, NCHW;
- mean: `[151.2405, 119.5950, 107.8395]`;
- per-channel scale: `[63.0105, 56.4570, 55.0035]`;
- output class 0 = real, class 1 = spoof;
- reported ACER: 3.81% on the upstream evaluation;
- model license: MIT according to Open Model Zoo legal information.

OpenVINO 2026.2 still lists this ONNX model as verified, which makes it a useful mature baseline even though Open Model Zoo itself is now in maintenance mode.

The published ACER is reference data only. It is not JARVIS Pocket-3 accuracy and must not become a JARVIS threshold.

The first Pocket-3 live run showed that feeding the tight YuNet face rectangle directly produced near-zero real probability for a genuine live OWNER. Upstream documentation confirms class 0 is genuinely the real class, so the result must not be "fixed" by swapping labels. A public anti-spoof-mn3 webcam integration expands the detected face roughly 10% left/right and 40% above the face before inference. JARVIS therefore added a research-matched contextual crop for a bounded retest. If that retest remains poor, this candidate will be rejected for the Pocket 3 rather than threshold-tuned into a pass.

## Candidate B — MiniFASNet multi-scale family

Primary lineage: MiniVision `Silent-Face-Anti-Spoofing`.

Benchmark packaging source: `yakhyo/face-anti-spoofing`, which provides compact ONNX exports of the MiniVision architecture.

Repository research revision: `aea85c1fa14e4d52a7910af75d59ef51e62a2267`.

GitHub release ID: `271938250` (`weights`).

Pinned assets:

- `MiniFASNetV1SE.onnx`
  - release asset ID `331026162`;
  - size 1,742,335 bytes;
  - SHA-256 `ebab7f90c7833fbccd46d3a555410e78d969db5438e169b6524be444862b3676`;
  - crop scale 4.0.
- `MiniFASNetV2.onnx`
  - release asset ID `331026163`;
  - size 1,743,581 bytes;
  - SHA-256 `b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907`;
  - crop scale 2.7.

The benchmark uses both models and averages their real-class probabilities. Class index 1 is treated as the real class, matching the published ONNX inference implementation.

MiniVision explicitly warns that RGB silent-liveness robustness depends on camera model and scene. That warning is a reason to benchmark on the Pocket 3, not a reason to copy published thresholds.

The code/model lineage is Apache-2.0, but the exact training-dataset provenance for these released MiniFAS weights is not sufficiently documented for a future commercial-distribution claim. They therefore remain benchmark candidates until that provenance question is explicitly reviewed.

## Runtime selection

Use ONNX Runtime `1.29.0` CPU inference for the benchmark.

Reasons:

- current release at research time;
- CPython 3.11 Windows x64 wheel available;
- both candidate families are tiny enough that CPU inference is appropriate;
- avoids introducing a CUDA-specific ONNX Runtime dependency merely for PAD;
- preserves provider/model replacement behind JARVIS-owned code.

## Benchmark architecture

```text
Pocket 3 read-only RGB
        ↓
YuNet full-frame face detection
        ↓
explicitly click one detected face
        ↓
short-lived face association in RAM
        ↓
┌────────────────────────────┐
│ anti-spoof-mn3             │
│ MiniFASNet V1SE + V2       │
└────────────────────────────┘
        ↓
per-frame real probabilities
        ↓
5-frame + 15-frame rolling medians
        ↓
distribution summary only
```

The benchmark deliberately selects a YuNet face directly rather than requiring a body track. A presentation attack such as a phone photo may have no genuine body behind the displayed face; requiring body association would hide the attack surface we are trying to measure.

The eventual runtime remains stricter: accepted PAD evidence must bind back to the same stable OWNER body/head track before it can contribute to trust.

## Benchmark output

For each candidate, report without inventing an accept threshold:

- valid sample count;
- real-probability min/p05/median/p95/max;
- inference latency median/p95;
- 5-frame rolling-median distribution;
- 15-frame rolling-median distribution.

Run the benchmark separately for each declared scenario. Human review compares live and attack distributions and decides whether either provider, their fusion, or neither is suitable.

## First real Pocket-3 live baseline — 2026-08-30

Scenario: real live enrolled OWNER, 300 samples, no frame/crop/tensor/output persistence.

Observed tight-crop `anti-spoof-mn3`:

- real probability: min 0.0006, p05 0.0008, median 0.0014, p95 0.0032, max 0.0060;
- rolling median 5: median 0.0014;
- rolling median 15: median 0.0013;
- latency: median 3.00 ms, p95 3.87 ms.

Observed MiniFASNet V1SE/V2 ensemble:

- real probability: min 0.9980, p05 0.9987, median 0.9994, p95 0.9997, max 0.9998;
- rolling median 5: median 0.9994;
- rolling median 15: median 0.9994;
- latency: median 12.37 ms, p95 26.16 ms.

Interpretation:

- MiniFAS is provisionally positive and extremely stable on this live OWNER run, but it is not accepted until phone-photo/video/print attack distributions are measured.
- tight-crop anti-spoof-mn3 is provisionally unsuitable on Pocket-3 + YuNet integration; contextual-crop retest is required before rejection.
- no threshold, liveness verdict, provider promotion, or T2 authority upgrade is approved from this run.

## Contextual-crop live retest — 2026-08-30

Scenario: real live enrolled OWNER, 300 samples, natural blinking and ordinary small eye/head movement permitted, no frame/crop/tensor/output persistence.

Observed `openvino-anti-spoof-mn3-reference-context-v1`:

- real probability: min 0.0008, p05 0.0014, median 0.0031, p95 0.0041, max 0.0049;
- rolling median 5: median 0.0031;
- rolling median 15: median 0.0031;
- latency: median 2.96 ms, p95 3.59 ms.

Observed MiniFASNet V1SE/V2 ensemble:

- real probability: min 0.9960, p05 0.9988, median 0.9995, p95 0.9998, max 0.9999;
- rolling median 5: median 0.9995;
- rolling median 15: median 0.9996;
- latency: median 9.12 ms, p95 30.66 ms.

Interpretation:

- contextual cropping does not recover anti-spoof-mn3 on the Pocket 3; genuine live OWNER remains near-zero real probability across the entire distribution.
- `anti-spoof-mn3` is therefore rejected as a JARVIS Pocket-3 passive PAD candidate rather than threshold-tuned into a pass.
- MiniFAS remains provisionally strong and stable on live OWNER across both independent 300-sample runs, including normal blinking and small natural movement.
- MiniFAS still must be tested against phone-photo, phone-video, and optionally printed-photo attacks before any threshold, liveness verdict, provider promotion, or T2 contribution can be approved.

## Decision rule after benchmark

Do not promote a passive provider merely because live scores look high.

Promotion requires demonstrated separation on the real Pocket 3 between live and the tested presentation attacks, reasonable stability across normal pose/distance/lighting, and explicit human acceptance. If separation is weak, passive PAD remains `UNCERTAIN` and 3B.7A active challenge stays the fallback.

## Future depth/IR upgrade

The liveness boundary must remain modality-neutral. When depth/IR hardware is added, JARVIS should be able to add or replace evidence providers for depth geometry, NIR response, structured illumination, or ToF without changing the authority contract.
