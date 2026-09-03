# Step 3 — Background Speaker Turn Ownership / Conversation Focus

Status: **ACTIVE RESEARCH + REAL-MACHINE BAKEOFF**

This slice was opened from a real production run on 2026-09-03. It is not a replacement for 3B.13 Sortformer overlap evidence; it solves a different problem discovered while accepting 3B.13 in the normal conversation runtime.

## Real-machine failure

With continuous human speech playing from a phone, JARVIS can recognize/generate a reply but repeatedly interrupts its own response until the phone stops.

The same run established that the identity sensors themselves are functioning:

- native Sortformer production shadow observed real concurrent-speaker activity (`peak_active=2`, overlap fraction `0.256`);
- LR-ASD produced a valid scored visual/audio window (`47/47` visual frames at `24.74 fps`);
- OWNER face+liveness context was `live_owner_candidate`.

The failure is therefore conversation turn ownership, not missing overlap evidence.

## Root cause in the current runtime

The accepted local barge-in gate is intentionally simple. During assistant playout, sustained Silero speech opens the gate after a short debounce. Once open, canonical microphone audio remains forwarded until Silero publishes end-of-speech.

A phone/TV producing continuous human speech has no silence boundary. The gate therefore remains open and Gemini's server-side automatic activity detector continues to see user activity. Gemini repeatedly cancels/interupts assistant output.

Changing only VAD sensitivity or silence duration would hide the symptom rather than establish who owns the conversational floor.

## Required architecture invariant

The canonical mixed stream must remain available to security and identity.

```text
Pocket3 microphone
      |
LiveKit MediaDevices / WebRTC AEC + NS + HPF + AGC
      |
canonical mixed PCM
      |
      +-----------------------------> security / identity
      |                                Sortformer
      |                                CAM++
      |                                LR-ASD
      |                                anti-spoof later
      |
      +--> conversation-focus filter --> wake / turn-taking / Gemini
```

Rules:

1. The focus filter is **UX input, never biometric truth**.
2. Sortformer/CAM++/LR-ASD continue observing the unfiltered canonical mixed PCM.
3. A successful focus filter must not erase overlap evidence from the security branch.
4. No provider/VAD threshold is changed merely to make this test pass.
5. Production integration waits for real-machine evidence.

## Current 2026 technology research

### LiveKit voice isolation — maturity reference

Current LiveKit documentation explicitly separates **voice isolation** from ordinary background-noise suppression. Voice isolation is intended to emphasize a primary speaker and reduce competing speech so STT, VAD, and turn detection receive cleaner input.

Current supported products include Krisp VIVA and ai-coustics Voice Focus 2.1 S/L. They are production-oriented and are the maturity/quality reference for this slice. They also add metering/licensing/authentication requirements and do not fit the current direct local `MediaDevices` architecture without additional integration work.

Disposition: **strong production reference / fallback, not first local bakeoff**.

### NVIDIA Maxine Audio Effects Speaker Focus

NVIDIA's client-side Audio Effects stack is architecturally attractive for this Windows RTX machine, and Speaker Focus is designed to isolate a primary speaker from other speakers. However, current access/licensing/product maturity around Speaker Focus is less frictionless than a normal public dependency.

Disposition: **strong local fallback if the open candidate cannot meet the real-machine gate**.

### Hush / `livekit-plugins-hush==0.3.3`

The current package is a self-hosted LiveKit `FrameProcessor` using the Hush speech-enhancement model. Relevant properties:

- Apache-2.0;
- no cloud API;
- pure NumPy DSP + ONNX Runtime;
- 16 kHz internal model with automatic LiveKit resampling;
- 10 ms streaming frames / approximately one-frame algorithmic latency;
- model explicitly trained with competing human speech;
- process-level shared ONNX model;
- package version `0.3.3` released 2026-06-26;
- upstream package labels itself Beta.

Upstream claims are not acceptance evidence. In particular, Hush documents that very loud competing speakers may not be completely suppressed.

Disposition: **first local benchmark candidate, not selected for production**.

Pinned package for the JARVIS bakeoff:

```text
livekit-plugins-hush==0.3.3
PyPI wheel SHA-256:
f7e18e96c86f53571cc97420d7d3e133c3830e7b4eddd6ba89dcccfc56a6c5cf
upstream source head for 0.3.3:
ab84d83864003d835013b4e914fca8df83b2cbc6
```

## Provider turn ownership after voice isolation

Gemini Live currently owns turn completion through server-side automatic activity detection. Google's current Live API supports disabling automatic VAD and sending explicit `activityStart` / `activityEnd` events from the client. LiveKit likewise supports local/manual turn detection when realtime-provider server detection is disabled.

This is important but is **not the first change** in this slice. A plain local VAD/turn detector still cannot know that continuous phone speech is not the user. First establish a clean conversation-focus signal. Then decide whether Gemini server VAD remains good enough or whether JARVIS should own activity boundaries.

Likely final layering if provider-native VAD remains unreliable:

```text
focused conversation PCM
        |
local activity / turn detector
        |
explicit activityStart / activityEnd
        |
Gemini Live with automatic activity detection disabled
```

No such change is accepted yet.

## Real-machine Hush bakeoff

New command:

```text
jarvis-conversation-focus-benchmark
```

It captures only memory-resident canonical PCM using the accepted MediaDevices path and evaluates:

- A — OWNER only;
- B — phone speech only, OWNER silent;
- G — OWNER + the same phone speech concurrently.

The same capture is evaluated at Hush strengths `0.5` and `1.0` by default.

For each condition JARVIS reports:

- raw and focused RMS/peak;
- raw and focused CAM++ OWNER cosine (diagnostic, no threshold/classification);
- score delta;
- total focus processing time / realtime factor;
- per-frame median and p95 processing latency.

No audio is written to disk. Production wake/Gemini input is unchanged.

### What good evidence should look like

We are not hard-coding an acceptance threshold before seeing real data. Qualitatively:

- A: OWNER speech should be preserved and CAM++ similarity should not collapse;
- B: phone-only speech should be materially attenuated;
- G: OWNER evidence should survive while competing speech is reduced;
- processing must have large realtime headroom on the actual machine;
- normal JARVIS UX must remain unaffected when eventually shadow-integrated.

If Hush cannot do this at the real phone volume that caused the failure, reject it and escalate to the stronger production candidates rather than weakening the acceptance criteria.

## Authority status

Unchanged:

```text
conversation focus        = benchmark only
Sortformer                = shadow evidence only
CAM++                     = shadow evidence only
LR-ASD                    = shadow evidence only
T2 CORROBORATED_OWNER     = disabled
R4                        = Windows Hello / T3
```

This slice changes no identity threshold and grants no action authority.
