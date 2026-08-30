# Step 3B.7B — Pocket 3 Passive RGB PAD Benchmark Evidence

Date: 2026-08-30

## Status

**REAL-MACHINE BENCHMARK EVIDENCE IN PROGRESS — NO PASSIVE PAD AUTHORITY YET**

This file records empirical DJI Pocket 3 benchmark evidence for the passive RGB presentation-attack-detection candidates researched in `STEP_3B7B_PASSIVE_RGB_PAD_RESEARCH.md`.

No raw frame, face crop, PAD tensor, or model output vector was persisted by these runs. No passive-PAD threshold, liveness verdict, provider promotion, or T2 trust upgrade was active during collection.

## Candidate disposition

### OpenVINO anti-spoof-mn3

**REJECTED for the current Pocket 3 integration.**

Two independent genuine-live OWNER runs remained near zero real probability, including a bounded retest using a reference-style contextual crop. Because upstream class semantics were verified as class 0 = real and class 1 = spoof, JARVIS does not relabel or threshold-tune this model into a pass.

### MiniFASNet V1SE + V2 ensemble

**LEADING PASSIVE RGB PAD CANDIDATE — NOT YET PROMOTED.**

The candidate has shown strong separation between genuine live OWNER and both static phone-photo and prerecorded phone-video presentation attacks. Promotion still requires a normal-use robustness sweep and explicit human acceptance of the resulting temporal decision rule.

## Live OWNER baseline 1

Scenario: genuine live enrolled OWNER, 300 samples.

MiniFASNet ensemble:

- real probability: min 0.9980, p05 0.9987, median 0.9994, p95 0.9997, max 0.9998;
- rolling median 5: median 0.9994;
- rolling median 15: median 0.9994;
- latency: median 12.37 ms, p95 26.16 ms.

OpenVINO anti-spoof-mn3 tight crop:

- real probability median 0.0014;
- rolling median 15 median 0.0013;
- latency median 3.00 ms.

## Live OWNER baseline 2 — contextual OpenVINO retest

Scenario: genuine live enrolled OWNER, 300 samples, with ordinary blinking and small natural eye/head movement.

MiniFASNet ensemble:

- real probability: min 0.9960, p05 0.9988, median 0.9995, p95 0.9998, max 0.9999;
- rolling median 5: median 0.9995;
- rolling median 15: median 0.9996;
- latency: median 9.12 ms, p95 30.66 ms.

OpenVINO anti-spoof-mn3 reference-context crop:

- real probability: min 0.0008, p05 0.0014, median 0.0031, p95 0.0041, max 0.0049;
- rolling median 15: median 0.0031;
- latency: median 2.96 ms.

Disposition: OpenVINO anti-spoof-mn3 rejected for Pocket 3.

## Phone-photo presentation attack

Scenario: clear static OWNER photo displayed full-screen on another phone, 300 samples.

MiniFASNet ensemble:

- real probability: min 0.0000, p05 0.0001, median 0.0152, p95 0.5231, max 0.8838;
- rolling median 5: median 0.0167, p95 0.2405, max 0.5217;
- rolling median 15: median 0.0148, p95 0.1100, max 0.2229;
- latency: median 8.34 ms, p95 30.18 ms, max 61.11 ms.

Interpretation: single-frame PAD decisions are unsuitable because isolated attack frames reached 0.8838 apparent real probability. Fifteen-frame temporal aggregation materially improved separation: attack maximum 0.2229 versus live OWNER rolling-median values around 0.9994–0.9996.

## Phone-video presentation attack

Scenario: prerecorded OWNER face video replayed on another phone, 300 samples.

The operator accidentally reselected the face after the first collection start, which correctly reset in-memory statistics to zero. The harness then reported `Need at least 120 samples before finishing; have 0.` Collection was restarted and a fresh complete 300-sample dataset was obtained. The final summary is therefore valid and contains no samples from before the reset.

MiniFASNet ensemble:

- real probability: min 0.0000, p05 0.0000, median 0.0000, p95 0.0005, max 0.0636;
- rolling median 5: min 0.0000, p05 0.0000, median 0.0000, p95 0.0006, max 0.0198;
- rolling median 15: min 0.0000, p05 0.0000, median 0.0000, p95 0.0000, max 0.0000;
- latency: median 8.06 ms, p95 27.33 ms, max 69.73 ms.

OpenVINO anti-spoof-mn3 reference-context crop:

- real probability: min 0.0002, p05 0.0003, median 0.0007, p95 0.0042, max 0.0240;
- rolling median 15: median 0.0007, p95 0.0039, max 0.0061;
- latency: median 3.05 ms, p95 3.84 ms.

Interpretation: the MiniFAS ensemble strongly rejected the prerecorded moving-face replay. The 15-frame rolling median remained 0.0000 through the complete reported distribution.

## Empirical separation so far

| Scenario | MiniFAS raw median | MiniFAS 15-frame median | MiniFAS 15-frame max |
| --- | ---: | ---: | ---: |
| Live OWNER run 1 | 0.9994 | 0.9994 | not required for acceptance comparison |
| Live OWNER run 2 | 0.9995 | 0.9996 | 0.9998 |
| Phone photo | 0.0152 | 0.0148 | 0.2229 |
| Phone video | 0.0000 | 0.0000 | 0.0000 |

This is strong empirical separation on the tested Pocket 3 conditions, but it is not yet a production threshold. A normal-use robustness sweep must establish how low genuine-live temporal scores can fall under moderate pose, distance, motion, and lighting variation before selecting LIVE / UNCERTAIN / SPOOF bands.

## Next acceptance evidence

Perform a genuine-live OWNER robustness sweep with normal non-cooperative behavior rather than an artificial still pose. Include moderate left/right yaw, slight up/down pitch, leaning nearer/farther from the camera, natural blinking/eye movement, and representative room-light variation where practical.

If genuine-live temporal scores remain clearly separated from the observed attacks, define a conservative three-state temporal rule:

- `LIVE`: strong sustained passive evidence;
- `UNCERTAIN`: insufficient or degraded evidence — invoke the already accepted 3B.7A active challenge when trust/risk requires it;
- `SPOOF`: strong presentation-attack evidence.

Even after passive PAD promotion, passive liveness remains supporting evidence only and must not independently grant T2 or authorize an action.
