# Step 3B.11 — LR-ASD score-distribution bake-off harness

Status: **IMPLEMENTED ON INTEGRATION BRANCH — REAL-MACHINE A-H RUN NEXT**

Date: 2026-09-02

## Purpose

The accepted single-microphone LR-ASD integration can produce real scores, but those scores are not yet calibrated for JARVIS. This harness exists to collect the first controlled positive, negative, ambiguous, insufficient, and AV-offset distributions from the actual JARVIS machine before any threshold or temporal rule is promoted.

No active-speaker threshold is selected by this implementation.

## Research-first decision

The harness deliberately reuses mature components instead of recreating them:

- **LR-ASD** remains the active-speaker model and official frontend/model implementation already accepted by Step 3B.11.
- **LiveKit MediaDevices/WebRTC APM** remains the only Pocket3 microphone owner and provides the canonical AEC + NS + HPF + AGC PCM used by the benchmark.
- **Existing JARVIS Vision** remains the only camera/track/head timeline.
- **Existing OWNER identity + passive liveness context** identifies the locked OWNER visual track used for LR-ASD evidence.
- **Existing LiveKit Silero VAD** performs the same speech-region gate used by the canonical production shadow path.
- **scikit-learn `precision_recall_curve`** provides exploratory threshold operating points instead of a hand-written metric implementation.
- **PyTorch CUDA events / CUDA peak-memory counters** provide synchronized GPU inference timing and allocation telemetry.
- **psutil** provides process CPU-time and resident-memory telemetry on Windows.

The only custom work is JARVIS-specific orchestration: canonical sensor capture, A-H scenario control, owner-track binding, AV-offset replay of the in-memory visual timeline, evidence classification, and derived-score reporting.

## Why AV-offset testing is mandatory

Active-speaker detection is supposed to depend on audio/visual synchrony, not merely the simultaneous presence of speech and a face. Published ASD synchronization research has shown that models can remain overconfident on deliberately unsynchronized audio/video. Therefore the harness tests the same captured speech region against shifted visual-source windows instead of assuming the current monotonic alignment is correct.

Default sweep:

```text
-300 ms
-200 ms
-100 ms
   0 ms
+100 ms
+200 ms
+300 ms
```

Shifted observations are diagnostic only and are never fed into binary threshold fitting.

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

## Scenario contract

| Key | Controlled scenario | Expected evidence class | Used for exploratory binary curve? |
| --- | --- | --- | --- |
| A | OWNER visible + OWNER speaks | positive | yes, 0 ms only |
| B | OWNER visible + off-camera/TV speech | negative | yes, 0 ms only |
| C | OWNER visible + JARVIS playback only | negative / ideally no canonical speech after AEC | yes if LR-ASD is reached |
| D | OWNER visible + OWNER replay from another device | negative | yes, 0 ms only |
| E | OWNER + other visible; OWNER speaks | positive | yes, 0 ms only |
| F | OWNER + other visible; other person speaks | negative | yes, 0 ms only |
| G | overlapping OWNER + other/background speech | ambiguous | no |
| H | temporary OWNER head loss while speaking | insufficient / fail closed | no |

G and H are safety-behavior tests. They are not coerced into positive/negative labels.

## OWNER track binding

At benchmark startup the operator stands alone in view. The harness waits for the already-accepted OWNER identity+liveness state, then calls the existing Vision `lock_only_confirmed_person()` control. The locked track ID and Windows session ID are retained for the A-H run.

Every scenario requires that same fresh locked OWNER context at its start. If the context has changed or disappeared, the scenario is marked `precondition_failed` rather than silently scoring another actor.

This is especially important for E/F, where a second visible person is introduced after the OWNER track has already been established.

## JARVIS playback scenario

Scenario C does not use an external recording. It invokes the existing provider-adapted `ScriptedSpeech` path through the already-open `MediaDevicesAudioOutput`.

This exercises the same physical speaker render that feeds the LiveKit/WebRTC AEC reverse stream. If AEC removes playback strongly enough that Silero finds no canonical speech, the scenario is recorded as `no_speech` with `jarvis_playback_removed_or_below_speech_gate`; LR-ASD is not forced to score silence.

## Frame-level LR-ASD trace

Production `LrAsdActiveSpeakerProvider` currently publishes aggregate mean/median/min/max values only. The benchmark needs the real temporal distribution.

To avoid changing production authority behavior, the harness uses a benchmark-only subclass that intercepts the already-computed output of `_multicontext_probabilities()`. It does not duplicate the LR-ASD model, frontend, MFCC logic, or checkpoint loading.

For each scored offset, the derived report stores:

- full averaged multicontext LR-ASD frame-score trace;
- mean / median / minimum / maximum;
- visual frame count and unique frame count;
- source FPS and maximum source gap;
- synchronized wall-clock inference latency;
- CUDA kernel timing when CUDA is active;
- CUDA baseline, peak allocation, and inference peak delta;
- process CPU seconds consumed;
- process RSS before and after inference.

## Exploratory threshold analysis

After the run, the harness calls `sklearn.metrics.precision_recall_curve` using only zero-offset scored traces from A/B/C/D/E/F.

Each scenario's frame scores receive weights summing to one, so a scenario with more frames cannot dominate only because it lasted slightly longer.

The report may expose exploratory operating points such as the maximum observed F1 point. These are evidence summaries only:

```text
DEPLOYMENT THRESHOLD SELECTED = FALSE
ACTIVE_OWNER_SPEAKER = DISABLED
```

One A-H run contains temporally correlated frame samples. It is the first real distribution, not deployment calibration. Human review of separation, temporal stability, negative tails, offset sensitivity, and G/H fail-closed behavior remains required before a temporal rule can be proposed.

## Persistence boundary

The benchmark writes one derived JSON report by default:

```text
step3b11_lr_asd_bakeoff.json
```

The report is git-ignored and contains scores/telemetry only.

It does **not** persist:

- raw microphone PCM;
- raw video;
- face/head crops;
- speaker embeddings;
- voiceprints;
- OWNER biometric templates.

## Installation

The benchmark dependencies are intentionally separate from production runtime dependencies:

```powershell
pip install -e ".[vision,active-speaker-benchmark]"
```

This installs the already-required LR-ASD frontend dependencies plus current pinned benchmark tooling (`scikit-learn` and `psutil`) without forcing those analysis packages into normal JARVIS installs.

## Run

From the repository virtual environment with the normal machine configuration already established:

```powershell
jarvis-active-speaker-benchmark
```

Default controlled capture duration is 4 seconds per scenario. The harness prompts before every scenario and permits `s` to skip or `q` to finish early.

Optional examples:

```powershell
jarvis-active-speaker-benchmark --seconds 5
jarvis-active-speaker-benchmark --offsets-ms=-300,-200,-100,0,100,200,300
jarvis-active-speaker-benchmark --output .\step3b11_lr_asd_bakeoff_run1.json
```

## Acceptance sequence after implementation

1. Pass repository formatting/lint/unit-test gates.
2. Run A-H once on the real JARVIS machine.
3. Review the generated JSON plus console zero-offset summaries.
4. Inspect positive/negative separation and negative maximum tails.
5. Inspect whether score quality degrades under deliberate AV offsets.
6. Confirm G remains ambiguous and H fails closed for lost visual continuity.
7. Only then define a candidate temporal rule and decide whether another controlled run is necessary.

Until that evidence is accepted, `active_speaker_confirmed` remains false, CAM++ prototype admission remains disabled, and T2 remains disabled.

## External references

- LR-ASD / Light-ASD official repository: `https://github.com/Junhua-Liao/Light-ASD`
- scikit-learn precision-recall API: `https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_curve.html`
- PyTorch CUDA semantics/timing: `https://docs.pytorch.org/docs/stable/notes/cuda.html`
- PyTorch CUDA peak allocation: `https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.max_memory_allocated.html`
- psutil documentation: `https://psutil.readthedocs.io/`
- Rethinking Audio-visual Synchronization for Active Speaker Detection: `https://arxiv.org/abs/2212.06470`
