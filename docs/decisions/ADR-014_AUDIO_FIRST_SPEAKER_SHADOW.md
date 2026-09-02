# ADR-014 — Audio-first parallel OWNER speaker shadow

Status: **ACCEPTED + REAL-MACHINE HUMAN-VALIDATED**

## Context

Step 3B.10 selected 3D-Speaker CAM++ as the provisional local speaker-embedding provider after a real JARVIS-machine bake-off. Healthy 2–3 second OWNER regions were materially separated from the observed TV speech samples, and CAM++ completed a roughly 3 second embedding in about 54 ms median on the deployment PC.

Step 3B.11 then established that LR-ASD is useful for answering whether the visible OWNER is speaking, but Scenario G demonstrated a different problem: when OWNER and another source speak at the same time, LR-ASD can correctly score OWNER as active while the whole microphone turn is still ambiguous.

JARVIS must gain useful day-to-day speaker awareness without making every conversation wait for a biometric gate or requiring the camera to see OWNER continuously.

## Decision

1. Normal user-turn audio remains owned by the accepted LiveKit MediaDevices/WebRTC AEC path.
2. Every committed user turn may be observed by a bounded memory-only speaker-shadow task outside the conversation critical path.
3. A local Silero speech-region detector trims the canonical turn. Short, quiet, clipped, missed, or otherwise rejected regions remain `INSUFFICIENT` and are not interpreted as non-OWNER.
4. Quality-qualified turns are scored against a strongly enrolled encrypted OWNER CAM++ prototype set.
5. CAM++ scoring and LR-ASD diagnostics may run in parallel when both are enabled.
6. Speaker similarity remains diagnostic only: no deployment threshold, OWNER classification, T2/T3 grant, action approval, or prototype auto-admission is enabled by this ADR.
7. Voice enrollment is an explicit OWNER operation. It captures multiple natural English/Hindi/Hinglish/near/far regions through the accepted microphone path, derives a bounded prototype set, discards raw audio, and updates the encrypted OWNER profile only after Windows Hello approves the exact profile commitment.
8. Normal conversation never self-enrolls or adapts the OWNER voice template.
9. Audio-only speaker shadow can operate with Vision disabled. LR-ASD still requires Vision.

## Alternatives considered

- **Block every conversation turn until speaker verification completes:** rejected because it deliberately worsens perceived latency and makes benign conversation dependent on a probabilistic biometric.
- **Verify OWNER only once per session:** rejected because speaker changes and later background/guest speech would inherit stale identity.
- **Auto-learn speaker prototypes whenever the face OWNER context is live:** rejected because replay, TV, and overlap can poison the voice profile before active-speaker/overlap acceptance is complete.
- **Require camera corroboration on every turn:** rejected as unnecessary friction for ordinary audio-only use.

## Real-machine acceptance

One-time OWNER voice enrollment passed on 2026-09-02:

- 12 accepted natural speech regions;
- 6 persisted CAM++ prototypes;
- embedding dimension 192;
- enrollment coverage cosine min `0.7593`, p05 `0.7749`, median `0.8726`;
- existing face profile preserved and VOICE added;
- raw audio not persisted;
- no speaker threshold or authority enabled.

The first ordinary JARVIS conversation with enrolled speaker shadow produced quality-qualified OWNER similarities:

- `0.7154` at `91.2 ms`;
- `0.6737` at `57.5 ms`;
- `0.7450` at `173.2 ms`;
- `0.7028` at `140.1 ms`.

Observed mean cosine was about `0.7092`; observed median embedding latency was about `115.7 ms`. CAM++ ran asynchronously and did not block normal responses. A `0.46 s` turn correctly failed quality as too short. One provider-understood turn was missed by local Silero (`max_vad_probability=0.2034`) and therefore stayed `INSUFFICIENT` rather than being misclassified.

This accepts the **non-blocking speaker-shadow architecture**, not an OWNER threshold.

## Why this choice

The accepted runtime already snapshots committed user audio into background shadow tasks, so CAM++ can add evidence without blocking provider transcription or response generation. The real-machine bake-off also showed CAM++ materially lighter than the tested ERes2NetV2 and TitaNet alternatives.

Strongly enrolled prototypes make normal runtime comparison read-only: conversation can compare against OWNER evidence but cannot redefine what OWNER sounds like.

## Consequences and tradeoffs

- Speaker similarity is available on sufficiently long/clean turns without intended conversation-path latency.
- Short follow-ups do not receive forced negative identity judgments.
- Audio-only CAM++ cannot prove liveness and may match replayed/synthetic OWNER speech.
- Scenario G is not solved by CAM++; a separate overlap/concurrent-speaker layer would be required before stronger audio-only or audio/visual authority promotion.
- Local Silero may occasionally miss otherwise provider-understood speech; that degrades to `INSUFFICIENT`.
- Because speaker/LR-ASD evidence remains non-authoritative and T2 is disabled, these limitations are accepted residual risks for Step-3 closure rather than reasons to keep Step 3 open indefinitely.

## Deferred strengthening

The following may be researched when a later product capability creates a concrete requirement:

- streaming overlap/speaker-change detection (for example, current mature Sortformer-class technology);
- replay/synthetic-voice countermeasures;
- direct non-OWNER human distributions and any threshold calibration;
- same-speaker continuity for very short turns;
- stronger multimodal composition/T2.

They are not automatically the next product slice.

## Replacement boundary

`EnrolledSpeakerShadowObserver` owns the embedding provider and encrypted prototype comparison. A future speaker model may replace CAM++ behind that boundary if it materially improves real JARVIS accuracy/latency without changing conversation ownership.

Overlap detection, anti-spoofing, LR-ASD, and speaker embeddings remain separate evidence producers.

## Conditions that should trigger reconsideration

Reconsider CAM++ or the per-turn policy if real use shows noticeable response latency, CPU contention, excessive short-turn insufficiency, poor far-field/Hinglish stability, insufficient separation from direct non-OWNER humans/replay, or if a later consequential capability needs voice evidence stronger than the current shadow boundary.
