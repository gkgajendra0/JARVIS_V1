# ADR-014 — Audio-first parallel OWNER speaker shadow

## Context

Step 3B.10 selected 3D-Speaker CAM++ as the provisional local speaker-embedding provider after a real JARVIS-machine bake-off. Healthy 2–3 second OWNER regions were materially separated from the observed TV speech samples, and CAM++ completed a roughly 3 second embedding in about 54 ms median on the deployment PC.

Step 3B.11 then established that LR-ASD is useful for answering whether the visible OWNER is speaking, but Scenario G demonstrated a different problem: when OWNER and another source speak at the same time, LR-ASD can correctly score OWNER as active while the whole microphone turn is still ambiguous.

JARVIS must gain useful day-to-day speaker awareness without making every conversation wait for a biometric gate or requiring the camera to see OWNER continuously.

## Decision

1. Normal user-turn audio remains owned by the accepted LiveKit MediaDevices/WebRTC AEC path.
2. Every committed user turn may be observed by a bounded memory-only speaker-shadow task that is already outside the conversation critical path.
3. A local Silero speech-region detector trims the canonical turn. Short, quiet, clipped, or otherwise rejected regions remain `INSUFFICIENT` and are not interpreted as non-OWNER.
4. Quality-qualified turns are scored against a strongly enrolled encrypted OWNER CAM++ prototype set.
5. CAM++ scoring and LR-ASD diagnostics run in parallel when both are enabled.
6. Speaker similarity remains diagnostic only: no deployment threshold, OWNER classification, T2/T3 grant, action approval, or prototype auto-admission is enabled by this ADR.
7. Voice enrollment is a one-time explicit operation. It captures multiple natural English/Hindi/Hinglish/near/far regions through the accepted microphone path, derives a bounded prototype set, discards raw audio, and updates the encrypted OWNER profile only after Windows Hello approves the exact profile commitment.
8. Normal conversation never self-enrolls or adapts the OWNER voice template.
9. Audio-only speaker shadow can operate with Vision disabled. LR-ASD still requires Vision.

## Alternatives considered

- Block every conversation turn until speaker verification completes: rejected because it deliberately worsens perceived latency and makes benign conversation dependent on a probabilistic biometric.
- Verify OWNER only once per session: rejected because speaker changes and later background/guest speech would inherit stale identity.
- Auto-learn speaker prototypes whenever the face OWNER context is live: rejected because replay, TV, and overlap can poison the voice profile before active-speaker/overlap acceptance is complete.
- Require camera corroboration on every turn: rejected as unnecessary friction for ordinary audio-only use.

## Why this choice

The accepted runtime already snapshots committed user audio into background shadow tasks, so CAM++ can add evidence without blocking provider transcription or response generation. The real-machine bake-off also showed CAM++ is materially lighter than the tested ERes2NetV2 and TitaNet alternatives.

Strongly enrolled prototypes make the runtime read-only: normal conversations compare against OWNER evidence but never redefine what OWNER sounds like.

## Consequences and tradeoffs

- Speaker similarity becomes available on essentially every sufficiently long/clean turn with no intended conversation-path latency.
- Short follow-ups do not receive forced negative identity judgments; later work may add fresh same-speaker continuity after overlap/speaker-change technology is accepted.
- Audio-only CAM++ cannot prove liveness and can match replayed/synthetic OWNER speech. Replay/deepfake countermeasures remain a separate required layer before voice can influence consequential authority.
- Scenario G is not solved by CAM++. Streaming overlap/diarization technology such as NVIDIA Streaming Sortformer remains the next research/acceptance slice.

## Replacement boundary

`EnrolledSpeakerShadowObserver` owns the embedding provider and encrypted prototype comparison. A future speaker model may replace CAM++ behind that boundary if it materially improves real JARVIS accuracy/latency without changing conversation ownership.

Overlap detection, anti-spoofing, LR-ASD, and speaker embeddings remain separate evidence producers.

## Conditions that should trigger reconsideration

Reconsider CAM++ or the per-turn policy if real use shows noticeable response latency, CPU contention, excessive short-turn insufficiency, poor far-field/Hinglish stability, or insufficient separation from direct non-OWNER humans/replay.
