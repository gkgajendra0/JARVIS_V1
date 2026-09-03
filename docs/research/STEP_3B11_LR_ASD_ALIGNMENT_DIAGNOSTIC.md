# Step 3B.11 — LR-ASD Alignment Diagnostic

Status: **DIAGNOSTIC IMPLEMENTED — REAL-MACHINE RUN REQUIRED**

Date: 2026-09-03

## Why this diagnostic exists

The first real-machine 1-second sliding turn-gate run produced a contradictory result:

- `B1_PHONE_ONLY`: mean `0.0147`, median `0.0033`, active fraction `0.000`;
- `G_OWNER_PLUS_PHONE`: mean `0.5193`, median `0.7535`, active fraction `0.550`;
- `B2_PHONE_ONLY`: mean `0.3237`, median `0.1029`, active fraction `0.300`;
- `A_OWNER_ONLY`: mean `0.0410`, median `0.0236`, active fraction `0.000`.

The phone-only negative separation was excellent, but the final genuine OWNER-only phase failed completely. Therefore no LR-ASD threshold or production gate may be promoted from that run.

## Research finding

LiveKit `MediaDevices` processes 10 ms microphone frames through WebRTC APM and uses PortAudio timing to estimate capture/render delay for AEC. JARVIS currently timestamps canonical processed audio when the routed frame is observed by the Python runtime, while Vision observations use the camera timeline. A fixed audiovisual offset is therefore a plausible explanation for the contradictory real-machine result and must be measured rather than guessed.

LR-ASD upstream inference also relies on temporally aligned audio/video and averages multiple temporal contexts. A one-second deployment gate must not be calibrated until canonical JARVIS timing is measured on the real machine.

## Diagnostic boundary

New command:

```text
jarvis-lr-asd-alignment-benchmark
```

The command is benchmark-only. It does not change:

- Gemini activity detection;
- production turn gating;
- speaker prototype admission;
- `active_speaker_confirmed`;
- T2/T3 authority;
- protected-action policy.

No raw audio, video, or face crops are persisted.

## Test design

The diagnostic captures two isolated six-second phases on the same accepted OWNER track:

1. `PHONE_ONLY`: OWNER remains visibly silent while continuous human speech plays from a phone.
2. `OWNER_ONLY`: phone is stopped; OWNER speaks continuously while remaining visible.

For each phase it prints canonical-audio proof before interpreting LR-ASD:

- capture duration;
- RMS dBFS;
- local Silero speech duration/fraction;
- speech segment count;
- maximum local VAD probability.

This separates `audio was not captured` from `audio/video were misaligned`.

## AV-offset sweep

The benchmark rescans the same memory-only evidence across visual-source offsets from `-1000 ms` through `+1000 ms` in `100 ms` increments by default.

To prevent the offset sweep from borrowing frames from another ground-truth state, all offsets are scored only inside a common settled interior margin equal to the larger of:

- the configured settle margin; or
- the maximum absolute swept offset.

For every offset it reports PHONE and OWNER median score, frame-level activity fraction at the diagnostic `0.50` reference, and median separation.

`best_diagnostic_offset` means only `largest measured OWNER-vs-phone separation in this one run`. It is **not** automatically applied to production.

## Settled one-second gate check

After the full-phase sweep, the harness evaluates settled one-second sliding windows at:

- `0 ms`; and
- the best diagnostic offset from this run.

Transition-contaminated prefix and tail windows are excluded from these distributions. This keeps classification evidence separate from the earlier continuous transition-latency experiment.

## Decision path

After the real-machine run:

1. If canonical OWNER speech is absent/weak, debug the audio capture path first.
2. If OWNER separation becomes clean at a stable non-zero offset, validate the offset with repeated samples before changing production timestamp alignment.
3. If no plausible offset restores OWNER-only discrimination while phone-only remains negative, test the LR-ASD TalkSet checkpoint as the same-architecture challenger.
4. Only after repeatable positive/negative distributions exist may a temporal rule or threshold be proposed.

Until then:

```text
production_turn_gate_enabled = False
LR_ASD_threshold_promoted = False
AV_offset_promoted = False
prototype_admission = False
T2_or_authority_effect = False
```
