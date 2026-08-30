# Step 3B.7B — Pocket 3 Passive RGB PAD Benchmark Evidence

Date: 2026-08-30

## Status

**HUMAN-ACCEPTED FOR THE CURRENT POCKET-3 PROTOTYPE — MINIFAS + 15-FRAME TEMPORAL FUSION SELECTED — NO T2 AUTHORITY YET**

This file records empirical DJI Pocket 3 benchmark evidence for the passive RGB presentation-attack-detection candidates researched in `STEP_3B7B_PASSIVE_RGB_PAD_RESEARCH.md`.

No raw frame, face crop, PAD tensor, or model output vector was persisted by these runs. No passive-PAD threshold, liveness verdict, provider promotion, or T2 trust upgrade was active during collection.

## Candidate disposition

### OpenVINO anti-spoof-mn3

**REJECTED for the current Pocket 3 integration.**

Two independent genuine-live OWNER runs remained near zero real probability, including a bounded retest using a reference-style contextual crop. Because upstream class semantics were verified as class 0 = real and class 1 = spoof, JARVIS does not relabel or threshold-tune this model into a pass.

### MiniFASNet V1SE + V2 ensemble

**SELECTED for the current Pocket-3 passive RGB PAD prototype.**

The candidate showed strong separation between genuine live OWNER, static phone-photo attack, prerecorded phone-video attack, and a normal-use live robustness sweep. It is used only behind JARVIS-owned 15-observation temporal fusion. It remains supporting biometric evidence, not permission and not a strong authenticator.

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

## Normal-use live robustness sweep

Scenario: genuine live OWNER with moderate left/right head turns, slight up/down movement, near/far leaning, normal blinking/eye movement, mouth movement, and ordinary small body/head movement. The operator reselected once and restarted; the reported final dataset is a fresh complete 300-sample run after that reset.

MiniFASNet ensemble:

- real probability: min 0.9073, p05 0.9878, median 0.9988, p95 0.9999, max 0.9999;
- rolling median 5: min 0.9383, p05 0.9913, median 0.9988, p95 0.9998, max 0.9999;
- rolling median 15: min 0.9855, p05 0.9942, median 0.9987, p95 0.9997, max 0.9998;
- latency: median 14.22 ms, p95 27.74 ms, max 43.63 ms.

OpenVINO anti-spoof-mn3 remained near zero and its rejection is unchanged.

Interpretation: the 15-frame temporal MiniFAS result remained strongly live throughout the normal-use movement sweep. The lowest observed genuine-live 15-frame median was 0.9855, while the strongest tested attack 15-frame value was 0.2229 from the phone-photo scenario.

## Empirical separation

| Scenario | MiniFAS raw median | MiniFAS 15-frame median | MiniFAS 15-frame min/max relevant to decision |
| --- | ---: | ---: | ---: |
| Live OWNER run 1 | 0.9994 | 0.9994 | stable live baseline |
| Live OWNER run 2 | 0.9995 | 0.9996 | max 0.9998 |
| Normal-use live robustness | 0.9988 | 0.9987 | **min 0.9855** |
| Phone photo | 0.0152 | 0.0148 | **max 0.2229** |
| Phone video | 0.0000 | 0.0000 | max 0.0000 at reported precision |

## Accepted temporal decision rule

For the current Pocket-3 prototype, JARVIS owns the temporal rule rather than trusting a single model frame:

- window: 15 fresh observations from the same Windows session, same visual track, and selected MiniFAS provider;
- `LIVE`: 15-observation median real probability >= 0.95;
- `SPOOF`: 15-observation median real probability <= 0.50;
- `UNCERTAIN`: between 0.50 and 0.95;
- `INSUFFICIENT`: fewer than 15 fresh observations;
- a gap greater than 0.50 seconds clears the temporal window;
- `UNCERTAIN` is eligible for the already accepted 3B.7A active challenge fallback;
- `SPOOF` fails closed rather than invoking a challenge automatically;
- passive evidence TTL is short-lived (2 seconds in the initial wiring).

These deliberately conservative bands leave substantial margin around the observed data instead of fitting thresholds to the benchmark extrema. They are specific to the selected Pocket-3/MiniFAS prototype and must be reevaluated when camera hardware, PAD model, crop behavior, or operating conditions materially change.

## Security boundary remains unchanged

Even after this human acceptance:

- passive PAD alone does not prove OWNER identity;
- passive PAD alone does not grant T2;
- passive PAD never authorizes an action;
- runtime trust must bind fresh OWNER face evidence and fresh liveness evidence to the same stable visual track and expected Windows session;
- critical actions still require T3 through Windows Hello/FIDO2;
- future depth/IR hardware may replace or strengthen this provider without changing the authority contract.
