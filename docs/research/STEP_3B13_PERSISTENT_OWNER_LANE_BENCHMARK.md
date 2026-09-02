# Step 3B.13 — Persistent Sortformer OWNER-lane benchmark

Status: **REAL-MACHINE GATE READY — PRODUCTION TURN GATING STILL OFF**

## Why this benchmark exists

The accepted native Sortformer overlap shadow can detect concurrent speakers, but a continuous external phone/TV voice can keep Gemini's server-side activity detection open and repeatedly interrupt JARVIS output. Generic Hush competing-speech suppression was rejected on the real machine because it barely attenuated the phone while significantly degrading OWNER CAM++ similarity.

The next hypothesis is narrower: JARVIS may not need waveform separation to decide conversational turn ownership. A single persistent Sortformer stream can expose stable speaker lanes and live per-frame probabilities. If one lane can be bound to OWNER and remains stable across speaker changes/overlap, the conversation layer can eventually end OWNER activity when that lane goes inactive even while another lane continues speaking.

No production conversation, trust, threshold, or authority behavior is changed by this benchmark.

## Upstream capability used

Pinned NeMo-Speech.cpp standalone diarization C ABI supports:

- a long-lived diarization stream;
- repeated mono float32 pushes;
- `frame_count` on a live unfinished stream;
- retained per-frame multi-speaker probabilities on a live unfinished stream;
- Sortformer v2 four-speaker capacity and 80 ms output frames.

The benchmark uses the same pinned native Windows/CUDA runtime and Sortformer model already accepted for the earlier 3B.13 overlap benchmark.

## JARVIS implementation

- `src/jarvis/identity/sortformer_live.py`
  - reusable persistent native stream wrapper;
  - opens one native diarization stream;
  - accepts caller-owned canonical PCM;
  - exposes live probability snapshots after each push;
  - never owns a microphone or grants authority.
- `src/jarvis/identity/sortformer_lane.py`
  - pure deterministic lane analysis;
  - no biometric authority threshold.
- `src/jarvis/identity/owner_lane_benchmark.py`
  - guided real-machine benchmark command: `jarvis-owner-lane-benchmark`.

## Guided sequence

Five 5-second captures are collected independently so the human can control the external phone, then concatenated and replayed through **one persistent Sortformer stream**:

1. `A1_OWNER_ONLY` — OWNER only.
2. `B1_PHONE_ONLY` — external phone human speech only.
3. `G_OWNER_PLUS_PHONE` — OWNER + same phone simultaneously.
4. `B2_PHONE_ONLY` — OWNER stops; same phone continues.
5. `A2_OWNER_ONLY` — phone stops; OWNER speaks again.

This deliberately tests the exact transition needed for the real bug: OWNER becomes inactive while a non-OWNER acoustic speaker remains active.

## Structural functional pass

The benchmark's functional pass is intentionally independent of CAM++ authority:

- the dominant A1 OWNER lane and A2 OWNER lane are the same;
- the dominant B1 phone lane and B2 phone lane are the same;
- OWNER and phone lanes are distinct;
- both lanes are concurrently active during G.

Latency is reported separately and requires human review before any production turn-gate decision.

## Latency telemetry

With a default 160 ms input push cadence, the benchmark reports live-stream availability for:

- initial OWNER lane acquisition;
- OWNER becoming inactive after A1 -> phone;
- overlap becoming visible after G starts;
- OWNER becoming inactive after G while the phone continues;
- OWNER lane reacquisition after B2 -> A2;
- native push median/p95/max compute time and overall RTF.

These values measure when the live API makes evidence available, not merely offline final-label accuracy.

## Security boundary

Still OFF:

- production OWNER-aware turn gating;
- CAM++ speaker authority threshold;
- T2 promotion from voice;
- actor authorization from Sortformer alone;
- any filtering of the canonical mixed security stream.

Raw capture audio stays memory-only and is discarded on exit.
