# Step 3 — Final Identity / Voice Security Research

Date: 2026-09-02

Status: **RESEARCH COMPLETE FOR FIRST BENCHMARK GATE — PRODUCTION AUTHORITY NOT YET PROMOTED**

## Purpose

Step 3 was reopened by explicit human decision before Step 4 because the accepted governance foundation and biometric evidence providers had not yet been composed into the complete graduated-trust / spoken-actor security path originally intended.

This research covers the already-known remaining gaps as one bounded final program:

1. Scenario G concurrent/overlapping speaker ambiguity;
2. speaker-change evidence and short-turn continuity;
3. direct non-OWNER CAM++ calibration;
4. replay/synthetic/cloned-voice countermeasures;
5. deterministic `IdentitySession` / `TrustEvaluator` composition;
6. spoken actor binding;
7. T2 integration with R1/R2/R3 authority while preserving T3/Windows Hello for R4.

No new model is permitted to directly grant authority. Sensors/models produce typed evidence only.

---

## Permanent security boundary

The original accepted Step-3 governance remains correct:

```text
IDENTITY EVIDENCE
      ↓
DETERMINISTIC TRUST
      ↓
EXACT-ACTION AUTHORITY
```

The following remain forbidden:

```text
voice score -> authenticated
face score -> permission
LR-ASD score -> permission
weighted weak signals -> strong authority
LLM confidence -> trust tier
```

Voice recognition is useful corroborating evidence but is not a password or strong authenticator. Critical R4 operations remain proposal-bound T3 / Windows Hello.

---

## 1. Scenario G — what signal is missing?

Existing real-machine evidence:

- clean visible OWNER speech: LR-ASD mean about `0.8676`;
- TV/off-camera speech: about `0.0014`;
- replayed OWNER voice while visible OWNER is silent: about `0.0014`;
- OWNER + concurrent other/background speech: about `0.8253`.

The G result is semantically reasonable: OWNER really is speaking. LR-ASD answers:

> Is the visible OWNER speaking?

It does **not** answer:

> Is OWNER the only speaker responsible for the mixed microphone turn?

Therefore the missing evidence must be independent concurrent-speaker / overlap / speaker-change activity.

Required JARVIS vocabulary:

```text
SINGLE_SPEAKER
OVERLAP_DETECTED
SPEAKER_CHANGE
AMBIGUOUS
INSUFFICIENT
```

This evidence is diagnostic until the full trust resolver is accepted.

---

## 2. Streaming diarization technology comparison

### Candidate A — NVIDIA Streaming Sortformer v2.1 through Python NeMo

Current upstream facts:

- official model: `nvidia/diar_streaming_sortformer_4spk-v2.1`;
- four-speaker streaming Sortformer;
- additional meeting-corpus training versus v2;
- published low-latency operating point around `1.04 s`;
- all published DER evaluations include overlapping speech;
- v2.1 materially improves meeting-speech DER versus v2;
- model artifact is roughly `471 MB` (`~492 MB` repository footprint);
- model license is NVIDIA Open Model License;
- NeMo source is Apache-2.0, model terms are separate.

Published examples at ~1.04 s latency include approximately:

- DIHARD III <=4 speakers: DER `15.09`;
- CALLHOME full: `11.19`;
- AliMeeting near: `12.60`;
- AliMeeting far: `15.60`;
- AMI IHM: `16.67`;
- AMI SDM: `20.57`.

Problem for JARVIS deployment:

- the current NeMo Framework support matrix explicitly lists native Windows x86-64 PyPI/source deployment as **not supported yet**;
- JARVIS is a native Windows desktop runtime;
- adopting a WSL/container sidecar only to reach v2.1 would add a second platform/runtime boundary, deployment complexity, latency/IPC risk, and operational fragility.

Disposition:

**ACCURACY REFERENCE / RECONSIDERATION TARGET, not the first native production candidate.**

Sources:

- https://github.com/NVIDIA-NeMo/Speech/tree/main/examples/speaker_tasks/diarization
- https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1
- https://pypi.org/project/nemo-toolkit-asr/
- https://docs.nvidia.com/nemo/labs-voice-agent/about/core-concepts/speech-pipeline/speaker-diarization/

### Candidate B — NVIDIA NeMo-Speech.cpp + Streaming Sortformer v2

NVIDIA released NeMo-Speech.cpp in 2026 as a lightweight local native inference runtime.

Relevant properties:

- native Windows x86-64 installation/build path;
- CPU/CUDA/Vulkan backends and Windows CUDA support;
- standalone Sortformer diarization;
- stable C ABI (`nemo_speech_diar_*`);
- streaming audio push API;
- raw per-frame speaker probabilities are exposed directly;
- four speakers supported;
- frame duration `0.08 s`;
- long-running streams bound probability memory while retaining finalized segments;
- local runtime, no cloud biometric processing required;
- source is Apache-2.0;
- current documented/converted diarization checkpoint is `nvidia/diar_streaming_sortformer_4spk-v2`.

The raw probability API is especially important. JARVIS should not copy NeMo Labs Voice Agent's high-level behavior of reducing a turn to one dominant speaker label. Scenario G requires inspecting simultaneous frame-level activity.

Operational concern:

- NeMo-Speech.cpp is a new `0.1.x`-era runtime and APIs may still evolve;
- documented model support is v2, not v2.1;
- therefore real JARVIS-machine latency/VRAM/contention and Scenario-G accuracy must decide adoption.

Disposition:

**PRIMARY NATIVE WINDOWS BENCHMARK CANDIDATE.**

Sources:

- https://github.com/NVIDIA/NeMo-Speech.cpp
- https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/install.md
- https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/include/nemo_speech/diar.h
- https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/model-conversion.md

### Candidate C — pyannote.audio Community-1

Strengths:

- current open-source diarization model;
- strong speaker counting/assignment improvements;
- overlap detection is part of the segmentation capability;
- self-hostable / offline.

Problem:

- pyannote's own current streaming FAQ says realtime/streaming speaker diarization is **not available out of the box**;
- it points users to `diart` for streaming.

Community-1 remains valuable as an offline accuracy/reference candidate if Sortformer v2 is not adequate.

Disposition:

**OFFLINE/REFERENCE CANDIDATE, not first realtime integration.**

Sources:

- https://www.pyannote.ai/blog/community-1
- https://github.com/pyannote/pyannote-audio/blob/main/questions/streaming.question.md

### Candidate D — diart / pyannote streaming

`diart` is the research implementation of overlap-aware low-latency online diarization built on pyannote segmentation/embedding models.

Strengths:

- genuine streaming/incremental diarization;
- overlap-aware research lineage;
- useful reference/backup.

Concerns for current JARVIS:

- additional PortAudio/FFmpeg/libsndfile-era deployment assumptions are unnecessary because JARVIS already owns canonical audio;
- its documented default environment is tied to older pyannote dependency arrangements;
- operational footprint is less attractive than the new NVIDIA native API for this Windows system.

Disposition:

**BACKUP RESEARCH CANDIDATE.**

Source:

- https://github.com/juanmc2005/diart (and maintained mirrors/forks where applicable)

---

## 3. First overlap technology decision

For the first real-machine benchmark:

```text
PRIMARY = NeMo-Speech.cpp + Sortformer v2
REFERENCE = Python NeMo Sortformer v2.1 published metrics
BACKUP = pyannote Community-1 / diart
```

Why v2 rather than forcing v2.1:

JARVIS's rule is not “pick the highest paper number.” It is “pick the best suitable mature technology for the actual deployment.” A native Windows official runtime that exposes the exact frame-level evidence JARVIS needs is currently a better production candidate than an accuracy-improved checkpoint behind a platform that its own framework says is unsupported on native Windows.

If native v2 fails the real-machine accuracy/performance gate, reopen v2.1 deployment options rather than weakening acceptance criteria.

---

## 4. Overlap architecture

No second microphone owner.

```text
Pocket3
  ↓
LiveKit MediaDevices / WebRTC APM
  ↓
canonical timestamped user PCM
  ├── realtime conversation
  ├── CAM++
  ├── LR-ASD
  └── Sortformer adapter
          ↓
     per-80ms activity probabilities
          ↓
     JARVIS overlap interpreter
          ↓
SINGLE / OVERLAP / CHANGE / AMBIGUOUS / INSUFFICIENT
```

Sortformer must never become the canonical conversation owner. It consumes a bounded canonical PCM tap.

Initial integration is shadow-only.

---

## 5. Sortformer benchmark gate

The benchmark must measure on the real RTX 5060 Ti machine while the accepted JARVIS stack is representative.

Required telemetry:

- runtime/model load success on native Windows;
- model/runtime version and artifact checksum;
- backend/device selected;
- per-chunk processing latency;
- end-to-end evidence delay;
- real-time factor;
- GPU VRAM before/load/peak/after;
- process RSS/CPU;
- contention while RF-DETR Vision is active;
- effect on CAM++ and LR-ASD timings;
- effect on realtime provider response/playback UX;
- probability trace for single-speaker and overlap windows.

Hard rejection/reconfiguration conditions:

- perceptible conversational slowdown;
- device/runtime instability;
- unacceptable VRAM pressure/contention;
- inability to distinguish the already-known G overlap from clean A speech;
- duplicate microphone ownership;
- only one dominant-speaker label available rather than concurrent frame activity.

No production threshold will be copied from a library default. A candidate threshold is calibrated from real JARVIS evidence.

---

## 6. Speaker identity calibration

Existing CAM++ evidence is mostly OWNER vs TV/replay. That is insufficient for a production OWNER-speaker threshold.

Required distributions before threshold promotion:

- OWNER normal near/far/quiet/English/Hindi/Hinglish;
- live non-OWNER human speech using the same microphone path;
- different durations, especially 2–3 s and longer clean regions;
- TV/podcast background speech;
- replayed OWNER speech;
- degraded/noisy conditions where scoring should become `INSUFFICIENT`.

Outputs remain:

```text
OWNER_SPEAKER_CANDIDATE
UNKNOWN_SPEAKER
AMBIGUOUS_SPEAKER
INSUFFICIENT
```

Never `AUTHENTICATED_BY_VOICE`.

---

## 7. Anti-spoof / cloned-voice technology landscape

Speaker embeddings answer “does this sound like OWNER?” and are not presentation-attack detection.

### ASVspoof5 official baselines

ASVspoof5 provides current challenge baselines for:

- RawNet2 countermeasure;
- AASIST countermeasure;
- spoofing-aware speaker verification (SASV), including score-fusion and integrated systems;
- evaluation metrics including a-DCF for spoofing-robust speaker verification.

This ecosystem is the strongest trustworthy evaluation starting point because it explicitly separates:

```text
speaker verification (ASV)
        +
spoof countermeasure (CM)
        ↓
spoof-aware speaker verification (SASV)
```

Sources:

- https://github.com/asvspoof-challenge/asvspoof5
- https://www.asvspoof.org/
- https://github.com/sasv-challenge/SASV2_Baseline

### AASIST

The official AASIST implementation:

- provides pretrained AASIST and AASIST-L checkpoints;
- is MIT-licensed;
- is an official ASVspoof baseline family;
- AASIST-L is very small (~85k parameters in the published repository).

However, the original pretrained checkpoint is built around ASVspoof2019 logical-access attacks. That benchmark success must **not** be interpreted as guaranteed detection of modern 2026 voice clones, replay through a room/phone, codec changes, or JARVIS-specific AEC/NS/AGC processing.

Disposition:

**PRIMARY COUNTERMEASURE BENCHMARK REFERENCE, not automatic production acceptance.**

Source:

- https://github.com/clovaai/aasist

### RawNet2

Useful independent official baseline, but older runtime/training assumptions and no obvious JARVIS operational advantage over AASIST.

Disposition:

**SECOND BENCHMARK REFERENCE.**

### Integrated SASV

The ASVspoof5/SASV challenge also publishes integrated spoof-aware speaker-verification research systems. These are scientifically valuable, but replacing the accepted CAM++ boundary immediately with an integrated research network would couple speaker identity and anti-spoofing prematurely.

JARVIS should initially keep them separate:

```text
CAM++ -> speaker similarity evidence
AASIST-class CM -> spoof evidence
```

Then the deterministic TrustEvaluator decides how evidence is composed.

Disposition:

**EVALUATION/FUSION REFERENCE; do not replace CAM++ before real evidence warrants it.**

---

## 8. Anti-spoof benchmark gate

The real JARVIS benchmark must include at least:

- live OWNER speech;
- live non-OWNER speech;
- OWNER recording replayed from phone/speaker;
- re-encoded/compressed OWNER recording;
- available synthetic/cloned OWNER-like speech generated only for defensive local evaluation;
- TV/podcast speech;
- JARVIS playback residual where captured;
- near/far and room-echo variation.

Record distributions, not one demo score.

Required output vocabulary:

```text
BONAFIDE_SUPPORTED
SPOOF_SUSPECTED
AMBIGUOUS
INSUFFICIENT
```

No countermeasure may claim proof of liveness or identity.

A spoof suspicion can reduce trust / force stronger verification. Absence of detected spoof must not by itself create OWNER authority.

---

## 9. Short-turn continuity

Current short speech such as `yes`, `why?`, `do it` may be too short for standalone CAM++ scoring. The correct solution is continuity, not a weaker voice threshold.

Only inherit fresh OWNER-speaker continuity if:

- same active JARVIS conversation;
- same Windows/authority session generation;
- recent high-quality OWNER speaker candidate;
- no speaker-change event;
- no overlap event;
- no spoof concern;
- no device reset/discontinuity;
- no conflicting actor evidence;
- inherited state is not the sole basis for critical authority.

Any violation returns `INSUFFICIENT` or `AMBIGUOUS`.

---

## 10. Missing IdentitySession / TrustEvaluator

The current authority layer already enforces `InteractionContext.trust_tier`, but a single authoritative runtime resolver does not yet derive that tier from evidence.

That composition layer is required before Step 3 can truly close.

Proposed responsibilities:

```text
IdentitySession
- current Windows/authority generation
- evidence window
- OWNER visual track binding
- current/last speaker actor binding
- freshness/invalidation
- ambiguity/spoof state

TrustEvaluator
- typed deterministic predicates only
- T0/T1/T2/T3 output
- reason codes
- no weighted score
```

### T0

No sufficient fresh OWNER context.

### T1

Fresh physical/session context exists but OWNER has not met the accepted T2 predicate.

### T2 baseline

Initial conservative predicate:

- expected active/unlocked Windows session;
- fresh OWNER face evidence;
- fresh accepted liveness;
- same visual track/session binding;
- no conflicting identity association;
- evidence inside frozen freshness windows.

Voice does **not** create T2 alone.

### Spoken actor association on top of T2

A voice-originated protected request/approval is `actor_unambiguous` only when current accepted evidence supports binding the spoken turn to OWNER.

Candidate composition after calibration:

- T2 baseline is live;
- current turn has accepted OWNER speaker-candidate evidence or safe short-turn continuity;
- LR-ASD supports visible OWNER speaking when Vision is available/relevant;
- overlap state is `SINGLE_SPEAKER` rather than overlap/ambiguous;
- spoof state is not suspected/ambiguous;
- turn/session/track IDs are consistent and fresh.

Failure does not demote all conversation; it makes the protected spoken actor ambiguous and triggers policy denial or strong-verification step-up.

### T3

Fresh successful strong platform verification (Windows Hello), still proposal/session bounded according to accepted authority rules.

---

## 11. Intended authority result

```text
R0 ROUTINE                  -> T0
R1 PRIVATE_READ             -> T2
R2 REVERSIBLE_LOCAL_CHANGE  -> T2
R3 PERSISTENT_OR_EXTERNAL   -> T2 + exact policy/approval
R4 CRITICAL                 -> T3 + Windows Hello
R5 RESTRICTED_DEV_ONLY      -> deny normal runtime
```

This is why the remaining voice/identity work matters: it provides natural, bounded OWNER trust for ordinary protected use without turning a voiceprint into a master credential.

---

## 12. Implementation decision for the next gate

Do not wire T2 or anti-spoof authority yet.

Next implementation is deliberately **benchmark-only**:

1. NeMo-Speech.cpp installation/readiness/model provenance probe;
2. bounded canonical-PCM Sortformer benchmark adapter;
3. frame-probability -> overlap/speaker-change diagnostic interpreter;
4. latency/RTF/VRAM/RSS telemetry;
5. guided real-machine A vs G benchmark.

If native Sortformer v2 passes, integrate it in production **shadow mode** and then proceed to calibration/anti-spoof/trust composition.

If it fails, revisit v2.1/pyannote alternatives rather than weakening the gate.

---

## 13. Final completion criteria

Step 3 cannot be marked DONE again until:

- overlap/speaker-change evidence is accepted or a documented alternative safely resolves G;
- direct non-OWNER speaker calibration exists;
- an accepted spoof-countermeasure disposition exists based on real JARVIS evidence;
- short-turn continuity is bounded by speaker-change/overlap/spoof semantics;
- one IdentitySession / TrustEvaluator owns T0/T1/T2/T3 derivation;
- spoken actor ambiguity is enforced by AuthorityService context;
- T2 works for intended bounded R1/R2/R3 scenarios;
- R4 remains Windows-Hello/T3;
- stale/cross-session/cross-track/replay/overlap/degraded tests fail closed;
- real-machine realtime UX/performance remains acceptable;
- E/F is collected with a real second person when available or explicitly handled by the final human acceptance decision;
- docs/CI/protected-main integration are reconciled.
