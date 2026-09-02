# Step 3B.11 — LR-ASD score-distribution bake-off harness

Status: **IMPLEMENTED + REAL-MACHINE EVIDENCE ACCEPTED FOR STEP-3 CLOSURE**

Date: 2026-09-02

## Purpose

The accepted single-microphone LR-ASD integration needed real JARVIS-machine evidence before any active-speaker threshold or temporal rule could be considered. This harness collected controlled positive, negative, ambiguous, insufficient, and AV-offset evidence while preserving the accepted production sensor boundary.

No active-speaker deployment threshold was selected.

## Research-first boundary

The harness reuses mature existing components rather than recreating them:

- **LR-ASD** official model/frontend implementation;
- **LiveKit MediaDevices/WebRTC APM** as the only Pocket3 microphone owner and source of canonical AEC + NS + HPF + AGC PCM;
- existing JARVIS Vision as the only camera/track/head timeline;
- existing OWNER identity + passive liveness context for locked OWNER track binding;
- existing LiveKit Silero VAD for speech-region extraction;
- scikit-learn for exploratory precision/recall analysis;
- PyTorch CUDA telemetry for GPU inference timing/allocation;
- psutil for process CPU/RSS telemetry.

Custom work is limited to JARVIS-specific orchestration: scenario control, canonical sensor capture, OWNER-track binding, AV-offset replay of the in-memory visual timeline, evidence classification, and derived-score reporting.

## Canonical runtime boundary

```text
Pocket3 microphone
      ↓
LiveKit rtc.MediaDevices only
AEC + NS + HPF + AGC
      ↓
ObservedSessionAudioInput
      ↓
bounded InMemorySpeakerTurnCapture
      ↓
LiveKit Silero speech-region gate
      ↓
LR-ASD audio frontend

Pocket3 video
      ↓
normal JARVIS Vision service
      ↓
locked OWNER track/head crops
      ↓
ActiveSpeakerVisualBuffer
      ↓
0 ms + shifted visual-source windows
      ↓
LR-ASD visual frontend
```

The benchmark never opens another microphone or camera.

## Scenario contract and accepted evidence

| Key | Controlled scenario | Expected class | Real-machine evidence | Step-3 disposition |
| --- | --- | --- | --- | --- |
| A | OWNER visible + OWNER speaks | positive | 0-ms mean `0.8676`, median `0.9248` | accepted clean positive |
| B | OWNER visible + off-camera/TV speech | negative | mean about `0.0014` | accepted strong negative |
| C | OWNER visible + JARVIS playback only | negative / ideally no canonical speech | `quality_rejected` | accepted fail-close; not threshold sample |
| D | OWNER visible + replay of OWNER voice from another device | negative | mean about `0.0014` | accepted replay negative for LR-ASD |
| E | OWNER + another visible; OWNER speaks | positive | not collected with a real second person | waived for Step-3 closure while T2/authority remain disabled |
| F | OWNER + another visible; other speaks | negative | not collected with a real second person | waived for Step-3 closure while T2/authority remain disabled |
| G | overlapping OWNER + other/background speech | ambiguous | mean about `0.8253` | accepted architecture-gap evidence; never binary threshold training |
| H | temporary OWNER head loss while speaking | insufficient | `insufficient` | accepted expected fail-close |

G and H remain safety/semantics evidence and are never coerced into positive/negative threshold labels.

## What Scenario G proved

Scenario G is not an LR-ASD failure. OWNER really is speaking, so a high active-speaker score is semantically reasonable. The missing question is whether OWNER is the **only** active speaker responsible for the mixed turn.

Therefore:

- LR-ASD may answer “is the visible OWNER speaking?”;
- LR-ASD alone may not authorize the entire mixed utterance as OWNER-only speech;
- future stronger audio/AV authority requires separate overlap / concurrent-speaker evidence;
- streaming diarization/overlap technology may be revisited later when a product capability needs it;
- Step 3 closes safely because `active_speaker_confirmed=False`, voice authority is disabled, and T2 remains disabled.

## AV-offset diagnostics

The harness supports shifted visual-source windows at:

```text
-300 ms
-200 ms
-100 ms
   0 ms
+100 ms
+200 ms
+300 ms
```

The clean OWNER A run remained high across the ±300-ms sweep. This is useful evidence that synchronization score alone must not be treated as a security/authorization signal. Shifted observations remain diagnostic only and are excluded from binary fitting.

## OWNER track binding

At benchmark startup the operator stands alone in view. The harness waits for already-accepted OWNER identity/liveness, locks that confirmed person, and retains the locked track ID + Windows session ID. Every scenario requires the same fresh OWNER context; missing/changing context fails the scenario precondition instead of silently scoring another actor.

## JARVIS playback scenario

Scenario C uses the existing `ScriptedSpeech` path through the accepted physical LiveKit MediaDevices output/AEC route. The observed canonical residual failed the speaker quality gate. This is retained as system-level fail-closed evidence; it is **not** claimed that AEC completely removed playback and it is not used as a scored LR-ASD negative sample.

## Frame-level / telemetry evidence

The benchmark records derived evidence only:

- averaged multicontext LR-ASD frame-score trace;
- mean / median / minimum / maximum;
- visual frame count and uniqueness;
- source FPS and maximum source gap;
- wall-clock/CUDA inference telemetry;
- CUDA allocation telemetry;
- process CPU/RSS telemetry.

No raw microphone PCM, raw video, face/head crops, speaker embeddings, voiceprints, or OWNER biometric templates are persisted.

## Exploratory threshold analysis

The harness can call `sklearn.metrics.precision_recall_curve` using only eligible zero-offset binary scenarios. The output is exploratory evidence only.

Final Step-3 state remains:

```text
DEPLOYMENT THRESHOLD SELECTED = FALSE
ACTIVE_OWNER_SPEAKER = DISABLED
T2 CORROBORATED_OWNER = DISABLED
```

The Step-3 product boundary does not require inventing a threshold merely because a benchmark can compute one.

## Installation / retained diagnostic use

```powershell
pip install -e ".[vision,active-speaker-benchmark]"
jarvis-active-speaker-benchmark
```

Focused examples remain available for future diagnostic work:

```powershell
jarvis-active-speaker-benchmark --scenarios A
jarvis-active-speaker-benchmark --scenarios E,F
```

E/F should use a real second visible person when revisited; photos/videos are not substitutes.

## Closure

The broad A–H bake-off is no longer the active work item. Step-3 closure evidence and residual risks are consolidated in:

`docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`

Future overlap/diarization, replay/deepfake hardening, E/F calibration, or threshold work should only be reopened when a later product capability creates a concrete requirement.

## External references

- LR-ASD / Light-ASD official repository: `https://github.com/Junhua-Liao/Light-ASD`
- scikit-learn precision-recall API: `https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_curve.html`
- PyTorch CUDA semantics/timing: `https://docs.pytorch.org/docs/stable/notes/cuda.html`
- PyTorch CUDA peak allocation: `https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.max_memory_allocated.html`
- psutil documentation: `https://psutil.readthedocs.io/`
- Rethinking Audio-visual Synchronization for Active Speaker Detection: `https://arxiv.org/abs/2206.10421`
