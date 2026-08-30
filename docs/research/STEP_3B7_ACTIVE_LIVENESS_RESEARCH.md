# Step 3B.7 Active Liveness Research

Status: implementation candidate pending automated validation and real-owner Pocket 3 acceptance.

## Goal

Produce fresh, same-track FACE_LIVENESS evidence that makes a static photo insufficient and raises the difficulty of generic prerecorded replay, without pretending RGB challenge-response is a strong biometric verifier.

## Technology decision

Use the already-pinned `mediapipe==1.0.1` runtime with Google MediaPipe Face Landmarker. The current Face Landmarker API can output face blendshapes and exposes a 52-coefficient blendshape vocabulary including bilateral eye blink, jaw open, and bilateral mouth smile. It supports VIDEO/LIVE processing modes and runs inference on-device.

Official API references reviewed 2026-08-30:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/drawing_styles/face_landmarker/Blendshapes
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarker

Official versioned model URL used by Google samples:

- https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

Pinned local integrity identity:

- size: 3,758,596 bytes
- SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`

The model is stored outside Git in the JARVIS external model cache. Existing cached bytes are verified before use; integrity mismatch fails closed rather than silently replacing the asset.

## Challenge design

Initial production candidate actions:

1. `BLINK`
2. `OPEN_MOUTH`
3. `SMILE`

Every fresh challenge randomizes all three actions without repetition using `secrets.SystemRandom`.

Each action requires a transition sequence:

`NEUTRAL -> ACTION -> NEUTRAL`

Each phase requires consecutive valid observations rather than one frame. A static image therefore cannot satisfy an action simply because it starts in the requested expression.

Initial thresholds are diagnostic candidates only and require real Pocket 3 acceptance/tuning:

- blink neutral: both eye-blink scores <= 0.30
- blink action: both eye-blink scores >= 0.60
- mouth neutral: jaw-open <= 0.25
- mouth action: jaw-open >= 0.55
- smile neutral: both smile scores <= 0.30
- smile action: both smile scores >= 0.50
- consecutive observations per phase: 2
- whole challenge TTL: 24 seconds

## Binding and fail-closed rules

A liveness challenge is bound to:

- exact Windows authority session ID;
- exact JARVIS visual body track ID;
- fresh challenge ID;
- fresh randomized action sequence;
- bounded challenge expiry.

The live harness fails if:

- Windows session changes/locks;
- visual track changes;
- selected target is lost beyond the bounded tolerance;
- associated head is lost beyond the bounded tolerance;
- challenge expires;
- the requested neutral/action/release sequence is not observed.

No cross-track evidence is accepted.

## Persistence and authority

The liveness path does not persist:

- raw camera frames;
- aligned face crops;
- face landmarks;
- blendshape vectors;
- liveness samples.

A successful challenge may create short-lived `FACE_LIVENESS` `IdentityEvidence` bound to the same visual track, but 3B.7 does not itself change trust or grant T2.

## Security limitation

This is active RGB challenge-response liveness, not a claim of robust presentation attack detection. Randomized action order and bounded timing make static photos fail and make generic prerecorded replay harder, but a sufficiently adaptive display/deepfake attacker may still defeat RGB-only challenge response.

Therefore:

- face liveness remains supporting evidence only;
- face match remains separate from liveness;
- T2 integration requires the wider corroboration chain;
- critical actions continue to require Windows Hello/FIDO2 strong verification;
- future depth/IR hardware or a dedicated PAD model may strengthen the liveness layer without changing the authority contract.
