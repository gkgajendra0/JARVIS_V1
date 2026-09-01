# Step 3B.10 — Speaker Identity / Corroboration Research

Date: 2026-08-31

## Status

**RESEARCH COMPLETE FOR BENCHMARK DESIGN — TECHNOLOGY BAKE-OFF NEXT — NOT IMPLEMENTED — T2/T3/AUTHORITY MUST NOT DEPEND ON VOICE**

## Goal

Add useful local speaker identity to JARVIS without repeating the brittle "voice authentication" design from the legacy JARVIS.

The desired system must answer a bounded question:

> Does the current sufficiently-good speech evidence support that the active speaker is the enrolled OWNER, an unknown speaker, or currently ambiguous?

It must **not** answer:

> Is this voice alone sufficient to authenticate the OWNER or authorize an action?

Speaker evidence is conversational/identity corroboration only. It never directly grants T2/T3, approves an action, or substitutes for Windows Hello/FIDO2.

## Security boundary

NIST SP 800-63B-4 explicitly states that biometric comparison based on voice shall not be used for authentication. It also emphasizes that biometrics are probabilistic and affected by noise/presentation variation.

Therefore JARVIS treats speaker recognition as typed evidence only.

Source:
- https://pages.nist.gov/800-63-4/sp800-63b.html

## Legacy JARVIS failure analysis

The old repository used `agents/speaker.py` with an ECAPA ONNX model. Its design was:

```text
WAV
 ↓
manual librosa MFCC frontend
 ↓
ECAPA ONNX embedding
 ↓
one averaged enrollment vector
 ↓
cosine similarity
 ↓
hard threshold 0.75
 ↓
True / False authentication
```

Important weaknesses:

1. **One centroid loses genuine voice variation.** Enrollment embeddings were averaged into one vector. Natural changes in pitch, energy, emotion, mic distance, language, and speaking style were collapsed.
2. **A fixed `0.75` threshold was assumed rather than calibrated on the actual microphone/runtime.** Vendor/repository thresholds are not deployment thresholds.
3. **The model frontend contract was reimplemented manually.** The old code generated 80-dimensional MFCCs with librosa and directly sent them to the ONNX model. The exact model provenance and its required preprocessing were not pinned/verified. Modern speaker models often require a very specific fbank/log-mel frontend and normalization contract. A frontend mismatch can make an otherwise good model appear unreliable.
4. **No speech-quality gate.** Very short, clipped, noisy, low-energy, AEC-corrupted, or non-speech regions could be scored anyway.
5. **No duration-aware semantics.** A short utterance such as `yes`, `no`, or `Jarvis` could become a hard rejection instead of `INSUFFICIENT`.
6. **No temporal evidence.** Every utterance was judged independently instead of allowing several good regions in one conversation to establish fresh speaker continuity.
7. **No ambiguity state.** The only output was Boolean match/non-match.
8. **No overlap/playback awareness.** TV audio, another person, JARVIS playback leakage, or overlapping speech could be scored as though one clean speaker were present.
9. **No replay/deepfake boundary.** Speaker similarity was implicitly treated as identity truth.
10. **Plain voiceprint persistence.** The old `voiceprint.json` was not protected by the Step-3 encrypted OWNER profile boundary.

### Primary lesson

The main mistake was not simply "ECAPA was bad." The architecture around it was brittle.

V1 must not recreate:

```text
one utterance + one embedding + one threshold = owner authentication
```

## Current JARVIS audio boundary to reuse

The accepted V1 audio runtime already owns exactly one physical microphone path:

```text
LocalAudioRuntime
    ↓
48 kHz mono / 10 ms frames
    ↓
AEC + noise suppression + high-pass + AGC
    ↓
JARVIS-owned router
    ├── local wake detector while idle
    └── AgentSession audio while active
```

Speaker evidence must tap this canonical processed PCM path. It must **not** open a second microphone stream.

Why:

- avoids device conflicts and duplicated capture;
- uses the exact audio JARVIS actually hears;
- preserves the accepted AEC/output-reference behavior;
- makes calibration representative of deployment;
- prevents a hidden secondary audio pipeline from drifting away from conversation truth.

Speaker models generally operate at 16 kHz, so the provider boundary may resample the canonical PCM deterministically while retaining the original timing/session metadata.

## Mature technology landscape

### 1. sherpa-onnx speaker embedding runtime — preferred deployment framework to benchmark

`sherpa-onnx` provides local ONNX speaker embedding extraction, speaker identification/verification helpers, `SpeakerEmbeddingManager`, microphone examples, and VAD integration. Its speaker extractor explicitly supports model families from WeSpeaker, 3D-Speaker, and NVIDIA NeMo.

This is attractive because JARVIS can delegate the model-specific feature extraction/frontend contract to the mature runtime instead of hand-writing MFCC/fbank preprocessing again.

Sources:
- https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html
- https://k2-fsa.github.io/sherpa/onnx/c-api/html/speaker_embedding.html
- https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/speaker-embedding-extractor-impl.cc
- https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py

**Disposition: ADOPT + WRAP for the benchmark/deployment runtime if the real-machine bake-off passes.**

### 2. 3D-Speaker CAM++ — strongest first deployment candidate

3D-Speaker publishes CAM++, ERes2Net, ERes2NetV2 and related models for speaker verification/recognition/diarization.

Relevant released choices include:

- `speech_campplus_sv_zh_en_16k-common_advanced` — CAM++ trained on a large Chinese-English corpus;
- `speech_campplus_sv_en_voxceleb_16k` — CAM++ trained on VoxCeleb;
- `speech_eres2net_sv_en_voxceleb_16k` — ERes2Net trained on VoxCeleb;
- `speech_eres2netv2_sv_zh-cn_16k-common` — ERes2NetV2 trained on a large common speaker corpus.

The sherpa-onnx project has a 3D-Speaker export path that writes model metadata including the exact framework, language, sample rate, feature normalization type, feature dimension, and output dimension. That is precisely the kind of pinned frontend contract missing from legacy JARVIS.

The Chinese-English CAM++ ONNX export is about 28.3 MB and an available mirrored upstream export has SHA-256:

`aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`

This checksum is a research lead only; before adoption JARVIS must pin the exact upstream release/model source and independently verify license/provenance.

Sources:
- https://github.com/modelscope/3D-Speaker
- https://github.com/modelscope/3D-Speaker/blob/main/speakerlab/bin/infer_sv_batch.py
- https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/3dspeaker/export-onnx.py

**Disposition: PRIMARY BENCHMARK CANDIDATE.**

Why CAM++ first:

- compact;
- designed for efficient speaker embedding extraction;
- mature 3D-Speaker ecosystem;
- ONNX/sherpa path available;
- Chinese-English training is likely a better domain starting point for a user who naturally mixes English/Hindi/Hinglish than an English-only model, although Hindi is not guaranteed by "Chinese-English" and real benchmarking must decide.

### 3. ERes2NetV2 — short-utterance specialist benchmark

Short speech is one of JARVIS's hardest cases. The ERes2NetV2 research specifically targets short-duration speaker verification and reports VoxCeleb1-O EER of approximately:

- `0.61%` full-duration;
- `0.98%` at 3 seconds;
- `1.48%` at 2 seconds.

This makes it scientifically relevant for short JARVIS turns.

However, the easily available 3D-Speaker pretrained ERes2NetV2 model is currently the Chinese/common model, while the VoxCeleb recipe and reported English benchmark do not automatically imply that the exact convenient released checkpoint is ideal for Hindi/Hinglish deployment.

Sources:
- https://www.isca-archive.org/interspeech_2024/chen24l_interspeech.html
- https://github.com/modelscope/3D-Speaker/blob/main/egs/voxceleb/sv-eres2netv2/README.md

**Disposition: BENCHMARK SHORT-DURATION REFERENCE, not automatic default.**

### 4. WeSpeaker — strong alternative, especially multilingual VoxBlink2 models

WeSpeaker publishes ONNX models including ECAPA, ResNet and newer multilingual VoxBlink2 SimAMResNet34/100 models. VoxBlink2 itself contains more than 100k speakers and is designed around large-scale/open-set speaker recognition.

The multilingual `SimAMResNet34` / `SimAMResNet100` models are attractive research candidates because they may generalize better across speaking/language variation than older English-only VoxCeleb embeddings.

However, model/export/runtime compatibility must be verified on the exact ONNX artifact before integration rather than assumed from the model table.

Sources:
- https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md
- https://arxiv.org/abs/2407.11510

**Disposition: BENCHMARK WILDCARD / potential accuracy winner.**

### 5. NVIDIA TitaNet-Large — mature accuracy reference, not preferred first runtime

TitaNet-Large is a 23M-parameter speaker embedding model. NVIDIA reports `0.66%` EER on cleaned VoxCeleb1 and notes that domain mismatch may require fine-tuning. sherpa-onnx supports NeMo speaker embedding exports such as `nemo_en_titanet_large.onnx`.

There are recent sherpa-onnx issue reports involving NaN/shape/runtime behavior and score differences for TitaNet ONNX exports. These are not proof that the model is unusable, but they make exact-version smoke testing mandatory.

Sources:
- https://huggingface.co/nvidia/speakerverification_en_titanet_large
- https://k2-fsa.github.io/sherpa/onnx/nemo/index.html
- https://github.com/k2-fsa/sherpa-onnx/issues/2818
- https://github.com/k2-fsa/sherpa-onnx/issues/2883

**Disposition: BENCHMARK REFERENCE, not default until runtime behavior is clean.**

### 6. SpeechBrain ECAPA-TDNN — independent accuracy/reference implementation

SpeechBrain's `spkrec-ecapa-voxceleb` is a mature Apache-2.0 model trained on VoxCeleb1+2. Its model card reports about `0.69%` EER on cleaned VoxCeleb1-test and the embedding checkpoint is about 83 MB.

It is valuable as an independent reference because it prevents JARVIS from assuming that a sherpa/ONNX pipeline is correct merely because it produces embeddings.

The downside is adding SpeechBrain/PyTorch framework coupling to a speaker path when V1 already has an ONNX-friendly deployment option.

Source:
- https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb

**Disposition: REFERENCE BENCHMARK, deploy only if it materially wins real JARVIS tests.**

## Why leaderboard EER is not enough

A model with excellent VoxCeleb EER can still be unpleasant for JARVIS because deployment conditions differ:

- very short commands;
- English/Hindi/Hinglish switching;
- quiet vs excited speech;
- near/far microphone positions;
- head turned away from microphone;
- consumer room acoustics;
- AEC/noise-suppression/AGC-processed PCM;
- JARVIS's own speaker output immediately before or during a user turn;
- TV/podcast/background voices;
- overlapping speech.

Therefore **no vendor/default similarity threshold will be accepted**.

Technology selection happens only after a real-device bake-off.

## Proposed architecture: Speaker Corroboration Engine

Do not implement `SpeakerAuth`.

Implement:

```text
JARVIS canonical processed PCM
            ↓
    speech-region segmentation
            ↓
       quality gate
  ┌─────────┼──────────┐
  │         │          │
 duration  signal    ambiguity
  │        quality   / playback
  └─────────┼──────────┘
            ↓
 sufficiently-good speech region?
       │              │
      no             yes
       │              ↓
 INSUFFICIENT    speaker embedding
                      ↓
             encrypted OWNER
             prototype-set comparison
                      ↓
        quality-aware temporal fusion
                      ↓
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
OWNER_SPEAKER     UNKNOWN       AMBIGUOUS /
_CANDIDATE        SPEAKER       INSUFFICIENT
```

### Never produce a Boolean "authenticated" result

The output vocabulary should initially be:

- `INSUFFICIENT`
- `OWNER_SPEAKER_CANDIDATE`
- `UNKNOWN_SPEAKER`
- `AMBIGUOUS_SPEAKER`

The evidence remains short-lived and session-bound.

## Quality gating before speaker comparison

Speaker embeddings should only be generated/scored for speech regions that pass bounded quality checks.

Candidate checks to benchmark/calibrate:

- minimum voiced duration;
- voiced/speech ratio from VAD/turn segmentation;
- clipping/saturation ratio;
- RMS/energy floor;
- excessive silence;
- spectral/noise quality proxy if useful;
- known JARVIS playback interval / AEC residual risk;
- overlapping-speaker ambiguity when detectable.

A poor-quality region produces `INSUFFICIENT`, **not `UNKNOWN_SPEAKER`**.

This distinction is central to avoiding the old "my own voice failed auth" problem.

## Short utterance policy

A phrase such as:

```text
yes
no
Jarvis
do that
```

must not independently create or revoke OWNER speaker identity.

Initial research rule:

- sub-second speech: likely `INSUFFICIENT` for standalone speaker classification;
- around 1–2 seconds: diagnostic/weak evidence only unless real calibration proves stable;
- >=2–3 seconds of clean voiced speech: normal candidate region for strong speaker evidence.

The exact duration bands are **not accepted yet**; the bake-off will measure them.

### Continuity for a short follow-up

Natural conversation should not require re-verifying every word.

A short `yes` may inherit **fresh same-speaker continuity** from a recent high-quality OWNER speaker region only if all of the following hold:

- same JARVIS/Windows session;
- same active conversation;
- recent OWNER speaker evidence is still fresh;
- no detected speaker change;
- no overlap/TV/playback ambiguity;
- no audio discontinuity/device reset;
- the short utterance is not being used as the sole biometric basis for consequential authority.

This is conversational continuity, not biometric authentication.

## Enrollment redesign

Do not store one mean voice vector.

Preferred V1 approach:

```text
Windows-Hello-gated OWNER speaker enrollment
        ↓
multiple natural speech regions
        ↓
model-owned embedding frontend
        ↓
quality filtering + outlier rejection
        ↓
bounded deterministic prototype set
        ↓
encrypted OWNER profile store
```

Enrollment should intentionally include ordinary variation:

- natural volume;
- quieter/louder speech;
- English;
- Hindi/Hinglish;
- typical near/far desk distance;
- several natural phrases rather than one repeated passphrase.

A practical target for research is approximately 30–60 seconds total clean speech split across multiple regions, not a long biometric ceremony.

Raw enrollment audio should be memory-only or temporary and deleted immediately after successful template construction. Persist only encrypted embeddings/prototypes and minimal model/version metadata.

### Prototype set rather than one centroid

As with the accepted face architecture, retain a small bounded set of representative OWNER speaker prototypes rather than averaging all voice variation into one point.

Candidate deterministic construction:

- normalized embeddings;
- quality/outlier rejection;
- centroid prototype;
- farthest diverse inlier prototypes;
- bounded count, initially perhaps 6–12 pending benchmark results.

The exact count/algorithm will be chosen after score-distribution analysis.

### Safe adaptation later

Never auto-learn from "the model thinks this is OWNER." That creates a poisoning path.

If adaptive speaker templates are added later, new samples may only be admitted during a strongly verified OWNER context (e.g. exact Windows Hello-gated enrollment/update operation) and through explicit template versioning/audit.

## Playback, TV, overlap and active-speaker ambiguity

Speaker embedding alone answers "this audio sounds like OWNER". It does **not** prove which visible person produced it.

That matters for:

- TV/podcast voices;
- prerecorded/streamed OWNER voice;
- another person in the room;
- JARVIS's own TTS leakage;
- overlapping speakers.

### Immediate V1 protections

- use the existing local output/AEC lifecycle to mark JARVIS playback windows;
- fail ambiguous rather than scoring obvious overlap/residual playback as a clean OWNER turn;
- never use wake-word confidence as identity;
- never use transcription/model confidence as identity.

### Audio-visual active-speaker provider — strong future/conditional addition

Light-ASD (CVPR 2023, MIT) is a lightweight audio-visual active-speaker detector. TS-TalkNet goes further by combining audio-visual synchronization with a pre-enrolled target speaker embedding.

This is conceptually very useful for JARVIS:

```text
speaker embedding says "sounds like OWNER"
+
active-speaker model says "selected OWNER face is producing this speech"
=
stronger actor corroboration
```

Unlike gaze attention, active-speaker detection does not require a fixed camera-to-monitor geometry; it relies on face/mouth motion and audio-visual synchronization. Therefore the movable Pocket 3 may still support it.

However, it should be benchmarked **only if ordinary audio-only speaker evidence cannot safely handle real multi-person/playback scenarios**, rather than becoming a heavy dependency by default.

Sources:
- https://github.com/Junhua-Liao/Light-ASD
- https://arxiv.org/abs/2305.12831
- https://github.com/Jiang-Yidi/TS-TalkNet

## Replay / deepfake resistance

ASVspoof 5 demonstrates that modern spoofing, neural-codec, adversarial, TTS and voice-conversion attacks remain a serious problem for speaker-verification systems.

Therefore:

- speaker identity remains corroborating evidence;
- a high similarity score is never treated as proof of live OWNER;
- existing face+liveness evidence remains separate;
- a future voice-spoof/countermeasure provider may add defensive evidence;
- no claim of perfect cloned-voice detection is allowed.

Source:
- https://arxiv.org/abs/2601.03944

## Model bake-off plan

Technology must be selected using the **actual canonical JARVIS processed microphone PCM**, not pristine saved WAVs from another recorder.

### Candidate A — 3D-Speaker CAM++ Chinese-English via sherpa-onnx

Primary deployment candidate.

### Candidate B — 3D-Speaker ERes2Net / ERes2NetV2

Short-duration/accuracy comparison.

### Candidate C — WeSpeaker multilingual VoxBlink2 SimAMResNet34

Multilingual generalization wildcard; use exact ONNX/runtime compatibility smoke test first.

### Candidate D — NVIDIA TitaNet-Large ONNX via sherpa-onnx

Mature independent architecture reference; reject if ONNX/runtime edge cases appear on our route.

### Candidate E — SpeechBrain ECAPA

Independent accuracy/reference pipeline, not preferred runtime unless it materially wins.

## Benchmark scenarios

### Genuine OWNER variation

Collect memory-only or explicitly temporary samples under normal JARVIS use:

- normal voice;
- quiet voice;
- louder/excited voice;
- English;
- Hindi;
- Hinglish;
- normal desk distance;
- farther/nearer distance;
- head facing microphone vs turned somewhat away;
- speech immediately after JARVIS playback;
- light background noise;
- durations around 0.5 s, 1 s, 2 s, 3 s, and 5+ s where practical.

We do not need to manufacture hoarseness or discomfort. Natural future sessions can expand robustness evidence later.

### Negative/ambiguity diagnostics without enrolling another person

Useful non-biometric negatives can be tested without storing another person's template:

- TV/news/podcast speech;
- YouTube speech;
- JARVIS TTS/output leakage;
- synthetic speech;
- prerecorded OWNER voice replay, if desired later;
- overlapping playback + live speech.

A live consenting non-owner remains ideal for final false-accept calibration, but its absence must not tempt JARVIS to invent an authoritative threshold.

## Metrics to record

For each candidate:

- embedding extraction latency;
- CPU/RAM footprint;
- embedding dimension;
- score distribution by utterance duration;
- genuine OWNER score distribution by language/style/distance;
- stability under AEC/NS/AGC processed audio;
- TV/playback/synthetic negative scores;
- percentage of regions rejected by quality gate;
- temporal/prototype-set separation;
- model asset size/checksum/provenance/license;
- frontend metadata (sample rate, fbank dimension, normalization, provider runtime).

Do not select the model solely from published EER.

## Threshold philosophy

No single threshold will be copied from a model README.

After the bake-off, define broad deployment states such as:

```text
strong sustained OWNER region → OWNER_SPEAKER_CANDIDATE
very weak similarity          → UNKNOWN_SPEAKER
middle / poor quality         → AMBIGUOUS or INSUFFICIENT
```

The exact bands require real-device positive and negative evidence.

Weak/short evidence never becomes strong merely by summing generic confidence scores.

## Interaction with T2 / authority

Speaker identity is **not required to be the sole creator of T2** and must never create T3.

Initial safety rule:

```text
speaker evidence alone
    ≠ T2
    ≠ T3
    ≠ approval
    ≠ execution permission
```

Speaker evidence can later:

- corroborate that a voice-originated turn is likely from OWNER;
- detect/flag a likely unknown speaker;
- preserve fresh speaker continuity during a natural conversation;
- support active-speaker/actor binding when combined with vision;
- make protected spoken interactions fail closed when the speaking actor is ambiguous.

Consequential authority still goes through immutable proposal → risk → policy → approval → final revalidation. R4 remains Windows Hello/FIDO2.

## Privacy

Default rules:

- do not persist raw conversation audio for speaker identity;
- do not retain unknown-speaker voiceprints;
- persist only the OWNER template explicitly enrolled/updated through the accepted encrypted profile boundary;
- record scalar/reason-code diagnostics only when necessary for acceptance/audit, without reconstructable audio;
- model/provider changes invalidate incompatible templates rather than silently reusing them.

## Proposed provider boundaries

```text
SpeakerRegionProvider
SpeakerQualityGate
SpeakerEmbeddingProvider
OwnerSpeakerTemplateStore / accepted OWNER profile store
TemporalSpeakerCorroborator
ActiveSpeakerProvider (optional/conditional)
VoiceSpoofProvider (optional/defense-in-depth)
```

JARVIS owns the evidence semantics and temporal state. Commodity models own feature extraction/embedding or specialist detection.

## Research decision

### Reject

- legacy Boolean `SpeakerAuth`;
- one averaged voiceprint as the only OWNER representation;
- hand-written MFCC/fbank preprocessing when the selected mature runtime owns the frontend;
- copied/default threshold;
- mandatory verification of every short utterance;
- speaker identity as permission/authentication;
- automatic enrollment/template adaptation from model confidence;
- full heavy diarization as the first dependency.

### Benchmark before adopting

1. **sherpa-onnx + 3D-Speaker CAM++ Chinese-English** — primary deployment candidate;
2. **ERes2Net/ERes2NetV2** — short-duration comparison;
3. **WeSpeaker VoxBlink2 multilingual SimAMResNet34** — multilingual wildcard;
4. **TitaNet-Large** — architecture reference;
5. **SpeechBrain ECAPA** — independent accuracy reference.

### Architecture direction

Adopt a **quality-aware, duration-aware, multi-prototype, temporal Speaker Corroboration Engine** instead of voice authentication.

## Next bounded action

Build a **diagnostic benchmark harness only**, not production trust logic.

The harness should:

1. tap the canonical JARVIS audio path rather than opening a second microphone;
2. segment speech using existing user-turn state and/or a mature VAD such as Silero VAD where needed;
3. run exact-model frontend/embedding extraction through the candidate's supported runtime;
4. keep raw benchmark audio memory-only by default;
5. compare candidate distributions across natural OWNER variation and safe playback negatives;
6. select one deployment provider from measured real-machine evidence;
7. only then define enrollment/prototype/temporal thresholds and return for human architecture approval before production implementation.
