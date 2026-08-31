# Step 3B.11 — Active-Speaker Corroboration Research

Status: **RESEARCH COMPLETE — LR-ASD IMPLEMENTATION + REAL JARVIS BAKE-OFF NEXT**

Date: 2026-08-31

## Why this slice exists

Step 3B.8 can establish that a live OWNER candidate is present. Step 3B.10 can establish that a speech segment resembles an OWNER voice prototype. Neither fact proves that the **currently visible OWNER produced the current microphone speech**.

That distinction is security-critical for passive voice learning.

Unsafe shortcut:

```text
live OWNER visible
        +
any microphone speech
        ↓
learn speech as OWNER
```

This can poison the OWNER voice bank with television audio, phone playback, an off-camera person, a second visible person, or overlapping speech while the OWNER remains visible.

Required boundary:

```text
fresh LIVE_OWNER_CANDIDATE
        +
exact visual actor sequence
        +
current canonical speech region
        ↓
audio-visual active-speaker corroboration
        ↓
only then eligible for session-only shadow prototype admission
```

Active-speaker evidence is corroboration only. It is not OWNER authentication and never grants execution authority.

## Non-negotiable architecture requirements

1. Do not open another camera or microphone.
2. Reuse the canonical Pocket-3 `CapturedFrame + VisionSnapshot` path and the canonical processed microphone PCM.
3. Bind a result to the same Windows session, visual track, and audio turn.
4. No visible face, multiple plausible speakers, overlap, timing discontinuity, or weak evidence must fail closed as `AMBIGUOUS` / `INSUFFICIENT`.
5. Speaker similarity must never bootstrap active-speaker truth.
6. Active-speaker confidence must never bootstrap OWNER identity.
7. Prototype admission remains disabled until a provider is accepted on the real JARVIS machine.
8. T2/T3 and protected-action authority remain unchanged.
9. Raw audio/video must not be persisted merely for active-speaker scoring.
10. Deployment behavior must be measured on the Pocket 3 + JARVIS AEC/NS/AGC route; no leaderboard threshold is accepted directly.
11. Provider/model code remains replaceable behind a JARVIS-owned contract.
12. Model assets stay outside the source repository and are integrity-checked before use.

## Refreshed 2026 technology scan

### 1. LR-ASD — selected first implementation

Official repository: `https://github.com/Junhua-Liao/LR-ASD`

LR-ASD is the IJCV 2025 extension of Light-ASD. The official repository is MIT licensed and, importantly for deployment, contains both inference code and pretrained model weights.

Official reported results include:

- AVA-ActiveSpeaker validation mAP: `94.45%`;
- Columbia average F1 using the AVA checkpoint: `86.1%`;
- Columbia average F1 using the TalkSet-finetuned checkpoint: `96.4%`.

A contemporary lightweight comparison reports LR-ASD at about `0.84M` parameters and `0.51G` FLOPs.

#### Exact upstream inference contract relevant to JARVIS

The official demo establishes the model-owned preprocessing contract:

- audio is mono `16 kHz`;
- audio features are `13-D MFCC` using a `25 ms` window and `10 ms` step, therefore approximately `100` audio feature frames/s;
- visual input is a temporal grayscale face sequence;
- the model consumes visual samples at `25 fps`;
- visual tensors are normalized by the upstream model before inference;
- the audio/visual temporal relationship is therefore `100:25 = 4:1`;
- the upstream demo averages several temporal-window scores rather than treating one frame as authoritative.

The original helper wrapper hardcodes CUDA in places and performs file/video-oriented preprocessing. JARVIS must **not** adopt that wrapper unchanged.

#### JARVIS integration rule

Use the mature LR-ASD network and official pretrained weights, but adapt only the integration boundary:

```text
JARVIS canonical 48 kHz PCM
        ↓
in-memory resample to LR-ASD 16 kHz
        ↓
official-equivalent 13-D MFCC frontend
        ↓
100 feature frames/s

exact JARVIS track/head frame sequence
        ↓
timestamp-select/resample to 25 fps
        ↓
LR-ASD grayscale face tensor

aligned audio + visual tensors
        ↓
LR-ASD model
        ↓
raw active-speaker score sequence
```

Do not:

- reopen the microphone;
- reopen the camera;
- write temporary WAV/video files;
- run LR-ASD's own face detector/tracker;
- use the upstream hard-coded `.cuda()` wrapper;
- accept its demo threshold as JARVIS authority.

The JARVIS provider chooses `cuda` when available and otherwise fails clearly or uses an explicitly accepted CPU path. It consumes in-memory data only.

Disposition: **PRIMARY IMPLEMENTATION + REAL-MACHINE BENCHMARK.**

### 2. LR-ASD TalkSet checkpoint — bounded same-architecture challenger

The official repository also ships a TalkSet-finetuned checkpoint. Because it uses the same architecture and preprocessing boundary, it is a low-cost second model candidate if the AVA checkpoint is fragile under conversational/far-field JARVIS conditions.

This is preferable to immediately integrating a second architecture: it lets the real machine tell us whether domain adaptation materially improves actor attribution with essentially zero integration churn.

Disposition: **WEIGHT-ONLY CHALLENGER IF NEEDED.**

### 3. C3ASD — robustness challenger, not first deployment

Official repository: `https://github.com/jisoo-o/C3ASD`

C3ASD is the ECCV 2026 consistency-driven lightweight ASD implementation. Published comparisons report roughly:

- `1.02M` parameters;
- `0.62G` FLOPs;
- `93.8%` AVA mAP;
- stronger robustness/cross-domain behavior than lightweight baselines under several corruption settings.

The public repository documents training/evaluation but does not currently provide as clear a ready-to-use pretrained deployment path as LR-ASD. Training a model ourselves before we have evidence LR-ASD fails would violate the research-first / mature-component principle.

Disposition: **FIRST ALTERNATE ARCHITECTURE ONLY IF LR-ASD REAL-MACHINE RESULTS ARE INADEQUATE AND A TRUSTED CHECKPOINT IS AVAILABLE.**

### 4. NVIDIA Active Speaker Detection NIM — evaluated, deferred

NVIDIA now provides an Active Speaker Detection NIM with streaming inference, CUDA/TensorRT/Triton acceleration, face processing, diarized audio input, and per-frame active-speaker outputs.

It is mature and commercially relevant, but it is the wrong first runtime for the current JARVIS slice because its supported deployment is a Linux NVIDIA-container/Triton service and its pipeline expects media plus diarization while also providing its own face-processing/tracking behavior.

For current JARVIS this would:

- introduce a separate Linux/Docker/Triton service into a Windows-local assistant;
- require diarization plumbing before the first streaming inference request;
- duplicate face/tracking work JARVIS already owns;
- add a substantially heavier operational/GPU footprint;
- weaken exact binding to the already accepted JARVIS visual track unless additional reconciliation logic is added.

Disposition: **FUTURE ENTERPRISE/PROVIDER OPTION, NOT THE 3B.11 LOCAL PRIMARY.**

### 5. GateFusion — promising research reference, deferred

GateFusion (WACV 2026) reports strong cross-domain active-speaker results using gated multimodal fusion. It is relevant as a future robustness challenger, but there is not currently a sufficiently clear production-ready public code + checkpoint path to justify replacing the deployable LR-ASD candidate.

Disposition: **WATCHLIST / FUTURE CHALLENGER.**

### 6. LASER / TalkNet / LoCoNet-family / graph methods — references

These systems remain useful independent baselines, especially for difficult multi-person or noisy scenes, but they generally add a heavier runtime and/or broader scene modeling than the first JARVIS requirement: determine whether the accepted visual OWNER track produced the current speech.

Disposition: **SECOND-WAVE / REFERENCE ONLY.**

## Runtime dependency decision

JARVIS already pins PyTorch `2.13.0` and torchvision `0.28.0` for the accepted vision stack. Do not introduce an older LR-ASD-era Torch environment or upgrade to a release candidate merely to mirror the research repository.

The provider will run against the existing accepted JARVIS Torch stack. Any incompatibility discovered on the real machine is handled at the provider boundary rather than by destabilizing the whole vision environment.

MFCC preprocessing is different from the CAM++ speaker path: CAM++ correctly uses sherpa/model-owned frontend behavior, while LR-ASD's published inference contract explicitly depends on its MFCC frontend. Therefore the LR-ASD provider may reproduce the exact upstream MFCC contract **inside the provider boundary**, with regression tests. That preprocessing must not leak into the canonical JARVIS audio architecture.

## JARVIS provider contract

The first implementation should expose a narrow JARVIS-owned interface rather than importing the upstream demo application.

Conceptual request:

```text
ActiveSpeakerWindow
- audio_turn_id
- windows_session_id
- visual_track_id
- start/end monotonic timestamps
- canonical mono int16 PCM @ 48 kHz
- timestamped exact head/face crops from the same selected track
```

Conceptual provider result:

```text
ActiveSpeakerAssessment
- provider/model identity
- evidence duration
- aligned audio/visual sample counts
- score statistics
- timing/alignment diagnostics
- state: SCORED / INSUFFICIENT / AMBIGUOUS / UNAVAILABLE
```

Important: the first provider returns calibrated **observations**, not an OWNER verdict. The JARVIS policy layer will define `ACTIVE_OWNER_SPEAKER` only after real-machine score distributions establish a safe temporal rule.

## Temporal/alignment design

The Pocket 3 is not assumed to produce exactly 25 fps. JARVIS must use timestamps and select/interpolate the accepted track's visual observations onto the provider's 25 fps grid.

Canonical audio remains 48 kHz everywhere else. The LR-ASD provider alone resamples the bounded turn/window to 16 kHz and computes its required MFCC features.

Initial benchmark windows should be bounded, starting around `1 s` and extending to `2 s` only where needed. No production minimum or threshold is accepted before measurement.

If a track/session changes inside a window, or if temporal coverage has a material gap, the result is insufficient rather than silently stitching different actors together.

## First bounded real-machine bake-off

Benchmark the **AVA LR-ASD checkpoint first**. Add the TalkSet checkpoint only if AVA behavior does not create a clean deployment boundary. Integrate C3ASD only if the same-architecture weight challenger is still inadequate.

Required scenarios:

```text
A. OWNER visible + OWNER speaking
B. OWNER visible + TV / phone / off-camera other person speaking
C. OWNER visible + JARVIS playback only
D. OWNER visible + OWNER playback from a phone
E. OWNER and another visible person, only OWNER speaking
F. OWNER and another visible person, only other person speaking
G. overlapping OWNER + other/background speech
H. OWNER head/face temporarily lost during an utterance
```

Measure:

- model/integration latency;
- GPU/CPU and memory footprint;
- raw score distributions;
- temporal stability on the same visual track;
- false active assignment to a silent OWNER face;
- off-camera speech behavior;
- playback/overlap behavior;
- sensitivity to audio/video timestamp offset;
- insufficient/ambiguous coverage rate.

No persistent voice enrollment is enabled during this benchmark.

## Intended acceptance path

```text
canonical user-turn PCM
        +
exact timestamped visual track/head sequence
        +
fresh LIVE_OWNER_CANDIDATE on the same track/session
        ↓
accepted active-speaker temporal rule
        ↓
ACTIVE_OWNER_SPEAKER / OTHER_OR_OFFCAMERA /
AMBIGUOUS / INSUFFICIENT
        ↓
ACTIVE_OWNER_SPEAKER only
        ↓
CAM++ session-shadow prototype admission
```

The active-speaker result is bound to `audio_turn_id + Windows session + visual_track_id` and expires quickly.

## Decision

- **Implement LR-ASD first using the official AVA pretrained checkpoint.**
- **Retain the official TalkSet-finetuned LR-ASD checkpoint as the first bounded challenger.**
- C3ASD remains the first alternate architecture if real JARVIS evidence requires it and a trusted checkpoint is available.
- NVIDIA ASD NIM is a future provider option, not the current Windows-local primary.
- GateFusion and heavier ASD families remain research references.
- Reuse JARVIS's existing Torch 2.13 stack.
- Do not vendor or run the LR-ASD demo pipeline; build a narrow in-memory provider adapter around the mature model/pretrained weights.
- Do not open secondary media devices or persist raw AV.
- No active-speaker threshold is accepted yet.
- No persistent voice enrollment is accepted yet.
- Passive CAM++ prototype admission remains **disabled** until active-speaker corroboration passes the real JARVIS test.

## Sources

- LR-ASD official repository / IJCV 2025 implementation: `https://github.com/Junhua-Liao/LR-ASD`
- Light-ASD official CVPR 2023 repository: `https://github.com/Junhua-Liao/Light-ASD`
- C3ASD official ECCV 2026 repository: `https://github.com/jisoo-o/C3ASD`
- NVIDIA Active Speaker Detection NIM documentation: `https://docs.nvidia.com/nim/maxine/active-speaker-detection/latest/`
- GateFusion, WACV 2026 paper: IEEE/CVF WACV 2026 proceedings
- LASER ASD implementation: `https://github.com/nawta/LASER_ASD_PyPI`
- TalkNet official implementation: `https://github.com/TaoRuijie/TalkNet-ASD`
