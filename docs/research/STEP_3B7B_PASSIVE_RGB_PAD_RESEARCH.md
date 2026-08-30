# Step 3B.7B — Passive RGB Presentation-Attack Detection Research

Date: 2026-08-30

## Status

**RESEARCH COMPLETE — REAL POCKET-3 BENCHMARK HUMAN-ACCEPTED — MINIFAS + TEMPORAL FUSION SELECTED FOR THE CURRENT RGB PROTOTYPE — NO T2 AUTHORITY YET**

Detailed empirical results are preserved in `STEP_3B7B_PASSIVE_RGB_PAD_BENCHMARK_RESULTS.md`. The architecture decision is recorded in `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`.

## Goal

Replace the normal-use requirement for explicit blink/smile/open-mouth challenges with mature passive RGB presentation-attack detection where evidence is strong enough, while retaining the accepted 3B.7A randomized active challenge as a deterministic fallback.

The current sensor is the DJI Pocket 3 RGB camera. Depth/IR remains a future provider upgrade and must not require redesigning JARVIS authority.

## Security boundary

Passive PAD is supporting biometric evidence, not permission and not a strong authenticator.

A model prediction of `real` must never directly grant T2 or authorize an action. Runtime trust must eventually combine fresh PAD with the same stable OWNER visual track, fresh OWNER face-match evidence, expected Windows session state, ambiguity checks, and the other accepted trust requirements. Critical actions still require T3 through Windows Hello/FIDO2.

No raw frame, face crop, PAD input tensor, or model output vector is persisted by the benchmark/runtime evidence boundary merely because it is available.

## Candidate A — OpenVINO `anti-spoof-mn3`

Upstream: OpenVINO Open Model Zoo.

Frozen research revision: `4d4266fbbb7eb5ab80944c2800d7f304868d573d`.

Model record:

- model: `anti-spoof-mn3.onnx`;
- size: 12,270,179 bytes;
- upstream checksum: SHA-384 `6de4534964b723397b3e8c995cadcf43bc007cc2f9930b95ae25f76adccece5d1d4d058d0b15117b9e4a9f758424f92a`;
- architecture: MobileNetV3 binary classifier;
- training dataset documented by upstream: CelebA-Spoof;
- input: RGB 128x128, NCHW;
- mean: `[151.2405, 119.5950, 107.8395]`;
- per-channel scale: `[63.0105, 56.4570, 55.0035]`;
- output class 0 = real, class 1 = spoof;
- reported upstream ACER: 3.81%;
- model license: MIT according to Open Model Zoo legal information.

### Pocket-3 disposition

**REJECTED.**

The initial tight YuNet crop produced near-zero real probability for genuine live OWNER. Upstream class semantics were verified, so JARVIS did not swap labels. A bounded retest using a reference-style contextual crop (approximately 10% left/right and 40% above the face) still left genuine live OWNER near zero.

The model therefore does not discriminate the Pocket-3 live condition in this integration and is rejected rather than threshold-tuned into a pass.

## Candidate B — MiniFASNet multi-scale family

Primary lineage: MiniVision `Silent-Face-Anti-Spoofing`.

Benchmark packaging source: `yakhyo/face-anti-spoofing`, which provides compact ONNX exports of the MiniVision architecture.

Frozen research revision: `aea85c1fa14e4d52a7910af75d59ef51e62a2267`.

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

The benchmark averages the two models' real-class probabilities. Class index 1 is treated as the real class, matching the published ONNX inference implementation.

MiniVision explicitly warns that RGB silent-liveness robustness depends on camera model and scene. JARVIS therefore does not copy a published threshold; it benchmarks the exact Pocket-3 path.

The code/model lineage is Apache-2.0, but exact training-dataset provenance for the released MiniFAS weights is not sufficiently documented for a future commercial-distribution claim. That issue remains an explicit future review item.

### Pocket-3 disposition

**SELECTED for the current prototype, behind JARVIS-owned temporal fusion.**

The real-machine benchmark demonstrated strong separation across:

- two genuine-live OWNER baselines;
- a static OWNER photo displayed on a phone;
- a prerecorded moving OWNER video replayed on a phone;
- a genuine-live normal-use robustness sweep with head/eye/mouth/body movement and distance variation.

Single-frame decisions are rejected because the phone-photo attack produced an isolated apparent-real score as high as `0.8838`.

The 15-frame temporal results were decisively separated:

- normal-use genuine-live minimum: `0.9855`;
- phone-photo attack maximum: `0.2229`;
- phone-video attack maximum: `0.0000` at reported precision.

## Runtime selection

Use ONNX Runtime `1.29.0` CPU inference for the current benchmark/runtime adapter.

Reasons:

- current compatible CPython 3.11 Windows x64 runtime at research time;
- candidate models are small enough for CPU inference;
- avoids introducing a CUDA-specific ONNX Runtime dependency solely for PAD;
- keeps model/provider replacement behind JARVIS-owned boundaries.

## Accepted temporal architecture

```text
Pocket 3 RGB
        ↓
selected/stable visual subject
        ↓
MiniFASNet V1SE + V2
        ↓
15 fresh observations
same Windows session + same visual track + same provider
        ↓
JARVIS temporal median
        ↓
LIVE / UNCERTAIN / SPOOF
```

Accepted prototype bands:

- `LIVE`: median >= `0.95`;
- `SPOOF`: median <= `0.50`;
- `UNCERTAIN`: between `0.50` and `0.95`;
- `INSUFFICIENT`: fewer than 15 fresh observations;
- gap > `0.50 s`: clear the temporal window;
- passive evidence TTL: initially `2.0 s`;
- `UNCERTAIN`: may invoke accepted 3B.7A active challenge;
- `SPOOF`: fail closed.

These thresholds deliberately leave substantial unused margin between observed live and tested attack distributions. They are not universal MiniFAS thresholds and must be re-benchmarked when the camera/model/preprocessing/operating envelope changes materially.

## Benchmark architecture and privacy

The diagnostic deliberately allowed direct YuNet face selection so photo/video presentation attacks could be measured even without a genuine body behind them. The eventual integrated runtime is stricter: liveness evidence must bind back to the same stable visual subject used by OWNER identity evidence.

The benchmark reports scalar distributions only. It does not save frames, face crops, PAD tensors, or output vectors.

## Future depth/IR upgrade

The liveness contract remains modality-neutral. Future depth, NIR, structured-light, stereo, or ToF providers may replace or strengthen the RGB provider without changing:

- identity evidence semantics;
- session/visual-track binding;
- trust tiers;
- action authority;
- Windows Hello/FIDO2 strong verification.

RGB PAD must not be represented as equivalent to depth/IR presentation-attack resistance.
