# ADR-008 — Step 3 Passive RGB Liveness

Date: 2026-08-30

## Context

Phase 3B needs liveness evidence that is strong enough for normal JARVIS presence verification without forcing the OWNER to perform blink/smile/mouth challenges during ordinary interaction.

The accepted 3B.7A MediaPipe active challenge remains useful, but its interaction cost makes it better as a fallback than as the default experience.

The current camera is a DJI Pocket 3 RGB sensor. Depth/IR sensing is intentionally deferred behind a replaceable liveness-provider boundary.

Research and real-machine evidence are recorded in:

- `docs/research/STEP_3B7B_PASSIVE_RGB_PAD_RESEARCH.md`
- `docs/research/STEP_3B7B_PASSIVE_RGB_PAD_BENCHMARK_RESULTS.md`

## Decision

For the current Pocket-3 prototype, adopt:

```text
Pocket 3 RGB
    ↓
selected/stable visual subject
    ↓
face/head crop
    ↓
MiniFASNet V1SE + V2 ensemble
    ↓
JARVIS-owned 15-observation temporal median
    ↓
LIVE / UNCERTAIN / SPOOF
```

The accepted temporal bands are:

- `LIVE`: median real probability >= `0.95`;
- `SPOOF`: median real probability <= `0.50`;
- `UNCERTAIN`: between `0.50` and `0.95`;
- `INSUFFICIENT`: fewer than 15 fresh observations.

A gap greater than `0.50` seconds clears the temporal window. Passive liveness evidence is short-lived; the initial evidence TTL is `2.0` seconds.

`UNCERTAIN` may invoke the already accepted 3B.7A randomized active challenge when liveness evidence is required. `SPOOF` fails closed rather than automatically challenging.

Every temporal window is bound to one Windows session, one visual track, and one PAD provider. Cross-session, cross-track, and cross-provider observations are rejected instead of fused.

Passive liveness remains supporting identity evidence only. It does not independently establish OWNER identity, grant T2, authorize an action, or replace Windows Hello/FIDO2 for T3.

## Alternatives considered

### OpenVINO `anti-spoof-mn3`

Rejected for the current Pocket-3 integration. Two genuine-live OWNER runs remained near-zero real probability, including a bounded retest using a reference-style contextual crop. Upstream class semantics were verified rather than relabeled. JARVIS will not threshold-tune a model until a live face passes.

### Single-frame MiniFAS decisions

Rejected. During the phone-photo attack an isolated frame reached `0.8838` apparent real probability even though the attack was correctly separated temporally. A single-frame decision would therefore create an avoidable replay/photo weakness.

### Active challenge as the normal path

Rejected as default UX. The active challenge is retained as a deterministic fallback for uncertainty.

### Building a custom anti-spoof classifier

Rejected. Mature PAD models are available and the project principle is to adopt mature commodity capability, then own the JARVIS evidence-fusion and authority boundaries.

## Why this choice

Real Pocket-3 evidence produced large separation:

- normal-use live robustness 15-frame minimum: `0.9855`;
- phone-photo 15-frame maximum: `0.2229`;
- phone-video 15-frame maximum: `0.0000` at the benchmark's reported precision.

The selected `0.95 / 0.50` bands intentionally leave substantial margin between the observed live and attack distributions rather than fitting thresholds to the extrema.

The normal-use sweep included moderate head turns, slight up/down movement, near/far leaning, natural blinking and eye movement, mouth movement, and ordinary small body/head movement.

## Consequences and tradeoffs

- Normal liveness can be passive and unobtrusive on the current RGB camera.
- Fifteen fresh observations add a small temporal delay before strong passive evidence exists.
- Degraded lighting, pose, occlusion, camera changes, or unseen attacks may produce `UNCERTAIN`; this is expected and must fail safely into the active challenge when needed.
- RGB PAD is not equivalent to depth/IR presentation-attack detection and must not be marketed or modeled as such.
- The current MiniFAS model lineage has an unresolved exact training-dataset provenance question for future commercial-distribution review.
- Model probabilities are not authority confidence. JARVIS owns the typed evidence state and downstream trust composition.

## Replacement boundary

`TemporalPassiveLiveness` owns temporal evidence fusion, while the PAD model remains replaceable behind the passive PAD provider contract.

Future depth/IR/ToF/structured-light providers may replace or augment the RGB provider without changing:

- the `IdentityEvidence` contract;
- visual-track/session binding;
- the trust-tier model;
- action authority;
- Windows Hello/FIDO2 strong verification.

## Conditions that should trigger reconsideration

Re-benchmark or replace this decision when any of the following changes materially:

- camera hardware or optical path;
- PAD model or model weights;
- face crop/preprocessing behavior;
- deployment environment or lighting envelope;
- evidence of new replay/presentation attacks that reduce separation;
- addition of depth, NIR, ToF, or structured-light hardware;
- commercial-distribution requirements that cannot accept the current MiniFAS weight provenance.
