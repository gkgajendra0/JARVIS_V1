# Step 3B.11 — Active-Speaker Corroboration Research

Status: **RESEARCH COMPLETE — REAL JARVIS BAKE-OFF NEXT**

Date: 2026-08-31

## Why this slice exists

The Step 3B.8 vision path can establish that a live OWNER candidate is present in front of JARVIS. The speaker-identity path can establish that a speech segment resembles an OWNER voice prototype. Neither fact proves that the **currently visible OWNER face produced the current microphone speech**.

That distinction is security-critical for passive voice enrollment.

Unsafe shortcut:

```text
live OWNER visible
        +
any microphone speech
        ↓
learn speech as OWNER
```

This permits profile poisoning by a nearby person, television, phone playback, or overlapping speaker while the OWNER remains visible.

Required boundary:

```text
fresh LIVE_OWNER_CANDIDATE
        +
current speech region
        +
audio-visual active-speaker corroboration
        ↓
only then eligible for session shadow prototype admission
```

Active-speaker evidence is still **corroboration, not authentication or execution authority**.

## Architectural requirements

1. Do not open another camera or microphone.
2. Use the canonical Pocket-3 frame/track/head association and the canonical processed microphone PCM.
3. Bind the decision to the same Windows session, visual track, and audio turn.
4. Treat no visible face, multiple plausible speakers, overlap, timing discontinuity, or low-quality evidence as `INSUFFICIENT` / ambiguous.
5. Never let speaker similarity bootstrap active-speaker truth.
6. Never let active-speaker confidence bootstrap OWNER identity.
7. Keep prototype admission disabled until a provider is real-machine accepted.
8. Keep T2/T3 and protected-action authority unchanged.
9. Do not retain raw audio/video merely for active-speaker scoring.
10. Benchmark deployment behavior on the actual Pocket 3 + JARVIS AEC/NS/AGC PCM rather than selecting from AVA leaderboard mAP alone.

## Current mature technology landscape

### 1. LR-ASD — primary first benchmark candidate

Repository: `https://github.com/Junhua-Liao/LR-ASD`

LR-ASD is the IJCV 2025 extension of the CVPR 2023 Light-ASD work. The official repository ships code and pretrained weights and is MIT licensed.

The 2026 C3ASD comparison table reports LR-ASD at approximately:

- `0.84M` parameters;
- `0.51G` FLOPs;
- `94.5%` AVA-ActiveSpeaker mAP.

Why it fits JARVIS:

- much smaller than classic TalkNet/LoCoNet-family models;
- explicitly designed around lightweight and robust active-speaker detection;
- audio-visual decision matches the exact question JARVIS needs: which visible face is producing the current speech;
- compute profile is attractive for a continuous local perception stack where RF-DETR, face identity, PAD, realtime voice, and other services already share the machine.

Disposition: **PRIMARY REAL-MACHINE BENCHMARK CANDIDATE.**

### 2. C3ASD — recent robustness challenger

Repository: `https://github.com/jisoo-o/C3ASD`

C3ASD is the official ECCV 2026 implementation of consistency-driven robust active-speaker detection. It builds on the lightweight ASD family and reports roughly:

- `1.02M` parameters;
- `0.62G` FLOPs;
- `93.8%` AVA mAP;
- stronger reported robustness/cross-domain behavior than the Light-ASD baseline under several audio corruption settings.

The paper/repository emphasizes inter-modality, intra-modality, and prediction-level consistency during training without adding inference-time cost beyond the resulting lightweight model.

Disposition: **ROBUSTNESS CHALLENGER** if LR-ASD proves fragile in JARVIS room noise, TV/background speech, distance, or overlap.

### 3. LASER — lip-landmark robustness challenger

Repository/package: `https://github.com/nawta/LASER_ASD_PyPI`

LASER is a WACV 2026 active-speaker implementation that injects lip-landmark information into a LoCoNet-style audio-visual system. The packaged implementation exposes a simple Python API and GPU acceleration.

Why it is relevant:

- lip motion can help when the audio scene is noisy or multiple faces are visible;
- directly attacks visual-speaking correspondence rather than generic face presence.

Why it is not the first choice:

- heavier LoCoNet lineage;
- another CUDA/PyTorch inference path in a runtime already carrying several perception models;
- the Pocket 3 can move and framing can vary, so landmark robustness needs to be measured rather than assumed.

Disposition: **SECOND-WAVE ROBUSTNESS REFERENCE.**

### 4. TalkNet — mature reference baseline

Repository: `https://github.com/TaoRuijie/TalkNet-ASD`

TalkNet is a mature ACM MM 2021 audio-visual active-speaker model and remains a useful independent reference implementation. A recent comparison table lists TalkNet at about `15.7M` parameters and `1.5G` FLOPs versus sub-million-parameter LR-ASD.

Disposition: **REFERENCE BASELINE**, not the preferred first production runtime.

## Why leaderboard mAP is not enough

JARVIS deployment differs materially from AVA-style video benchmarks:

- one movable gimbal camera rather than edited video;
- close and far owner speech;
- English/Hindi/Hinglish conversation;
- AEC/NS/AGC-processed 48 kHz canonical PCM;
- JARVIS's own speaker output immediately before or during user speech;
- TV/podcast/phone playback in the room;
- one visible owner while a different off-camera person speaks;
- multiple visible people;
- overlapping speech;
- short conversational turns;
- temporary face/head loss when the owner turns away.

Therefore no upstream active-speaker threshold will be promoted directly into JARVIS.

## First bounded real-machine bake-off

Benchmark **LR-ASD first** on the existing JARVIS frame/audio routes. Add C3ASD only if LR-ASD does not produce a sufficiently clean deployment boundary.

Minimum scenarios:

```text
A. OWNER visible + OWNER speaking
B. OWNER visible + TV / phone / off-camera other person speaking
C. OWNER visible + JARVIS playback only
D. OWNER visible + OWNER playback from a phone
E. OWNER and another visible person, only OWNER speaking
F. OWNER and another visible person, only other person speaking
G. overlapping OWNER + other/background speech
H. owner face/head temporarily lost during an utterance
```

Measure:

- end-to-end active-speaker latency;
- CPU/GPU and memory footprint;
- score distributions rather than one-off outcomes;
- temporal stability on the same visual track;
- false active assignment to a silent OWNER face;
- behavior with off-camera speech;
- behavior during playback/overlap;
- timing alignment tolerance between camera and canonical PCM.

No persistent voice enrollment is enabled during this benchmark.

## Intended integration after acceptance

```text
canonical LiveKit user turn PCM
        ↓
quality gate
        +
exact-frame visual track/head sequence
        +
fresh LIVE_OWNER_CANDIDATE
        ↓
active-speaker provider
        ↓
ACTIVE_OWNER_SPEAKER / OTHER_OR_OFFCAMERA /
AMBIGUOUS / INSUFFICIENT
        ↓
ACTIVE_OWNER_SPEAKER only
        ↓
CAM++ session-shadow prototype admission
```

The provider result is bound to `audio_turn_id + Windows session + visual_track_id` and expires quickly.

## Decision

- **LR-ASD is the primary candidate for the first JARVIS active-speaker bake-off.**
- **C3ASD is the first robustness challenger.**
- LASER and TalkNet remain reference/fallback implementations.
- No active-speaker threshold is accepted yet.
- No persistent voice enrollment is accepted yet.
- Passive CAM++ prototype admission remains **disabled** until active-speaker corroboration passes the real JARVIS test.

## Sources

- LR-ASD official repository / IJCV 2025 implementation: `https://github.com/Junhua-Liao/LR-ASD`
- Light-ASD official CVPR 2023 repository: `https://github.com/Junhua-Liao/Light-ASD`
- C3ASD official ECCV 2026 repository and comparison/robustness tables: `https://github.com/jisoo-o/C3ASD`
- LASER ASD packaged official implementation: `https://github.com/nawta/LASER_ASD_PyPI`
- TalkNet official ACM MM 2021 repository: `https://github.com/TaoRuijie/TalkNet-ASD`
