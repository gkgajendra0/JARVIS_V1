# Step 3 — Attention and Intent Evidence Amendment

**Status:** RESEARCH COMPLETE — AMENDMENT PROPOSED — AWAITING HUMAN APPROVAL — NOT IMPLEMENTED  
**Date:** 2026-08-30  
**Applies to:** `STEP_3_IDENTITY_TRUST_AUTHORITY_RESEARCH.md`, `STEP_3_THREAT_PRIVACY_MODEL.md`, and `STEP_3_ARCHITECTURE_PROPOSAL.md`

This amendment adds an explicit **attention / intent-to-engage** signal to Step 3. It borrows the useful security and interaction principle from Apple Face ID — a recognized face is not enough; the person should be actively attending to the device for certain protected interactions — without claiming that the DJI Pocket 3 can reproduce Face ID hardware security.

## 1. Why this is needed

The current Step-3 proposal distinguishes identity evidence, trust, and authority correctly, but it does not explicitly model the difference between:

- the OWNER being visible in the camera; and
- the OWNER deliberately looking toward JARVIS and engaging with it now.

That distinction matters for privacy and accidental authorization. JARVIS should be able to know that the owner is present while still refusing to disclose private information or accept a consequential spoken approval when the owner is looking elsewhere, asleep, distracted, or not clearly engaging with JARVIS.

The amendment therefore adds a short-lived typed evidence source:

`ATTENTION`

Attention is **evidence of current intent to engage**, not identity, authentication, or permission.

## 2. Apple design lesson — ADOPT THE PRINCIPLE, NOT THE CLAIM

Apple Face ID explicitly confirms attention and intent by checking that the user's eyes are open and attention is directed at the device. Face ID then uses the TrueDepth system to project/read thousands of infrared points, capture an infrared image, and perform matching/anti-spoofing inside the Secure Enclave. Apple also randomizes the capture sequence/pattern to make replay and spoofing harder. After five unsuccessful Face ID matches, the passcode is required.

The important JARVIS lesson is:

```text
recognized face
    !=
current user intent
```

and:

```text
identity + fresh attention
    is stronger interaction evidence than
identity alone
```

JARVIS must **not** claim Face-ID-equivalent security. The Pocket 3 is an RGB camera and does not provide Apple's TrueDepth IR/depth pipeline, device-specific projected patterns, sensor-to-Secure-Enclave binding, or Secure Enclave biometric matching.

Also, Face ID is **not iris authentication**. Apple's iris-based biometric system is Optic ID on Vision Pro. JARVIS may use eye/iris landmarks to estimate attention, but it must not describe that as iris scanning or iris authentication.

Primary sources:

- https://support.apple.com/guide/security/biometric-security-sec067eb0c9e/web
- https://support.apple.com/en-in/102381

## 3. Technology decision

### 3.1 MediaPipe Face Landmarker — PREFERRED INITIAL ATTENTION PROVIDER

The already-proposed MediaPipe Face Landmarker exposes facial landmarks and 52 blendshape coefficients including eye blink and eye-look directions. Its face landmarks also include eye/iris geometry.

This makes it the lowest-complexity first candidate because Step 3 already proposes MediaPipe Face Landmarker for active liveness. JARVIS should reuse the same bounded selected-head crop and avoid creating another full camera pipeline.

Important limitation: MediaPipe's historical Iris solution explicitly states that iris tracking itself does **not** infer where a person is looking. Therefore JARVIS must not treat iris-center geometry alone as a reliable gaze detector. The initial attention classifier should combine multiple signals such as:

- left/right eye-open state;
- eye-look blendshapes;
- head pose / facial transformation;
- eye/iris landmark geometry;
- temporal stability across several frames;
- same-track continuity.

The final decision threshold must be calibrated on the real Pocket 3 environment.

Sources:

- https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/vision/face_landmarker.py
- https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/iris.md

**Decision candidate:** `ADOPT + WRAP` MediaPipe Face Landmarker behind a JARVIS-owned `AttentionEvidenceProvider`.

### 3.2 OpenVINO `gaze-estimation-adas-0002` — BENCHMARK FALLBACK

OpenVINO's `gaze-estimation-adas-0002` accepts left-eye/right-eye crops plus head-pose angles and outputs a 3-D gaze vector. OpenVINO's 2026.2 verified-model table still lists this model as passing on supported backends.

It is a useful fallback benchmark if the MediaPipe-derived classifier does not reliably separate `looking toward JARVIS` from `looking away` on the Pocket 3.

Sources:

- https://docs.openvino.ai/2023.3/omz_models_model_gaze_estimation_adas_0002.html
- https://docs.openvino.ai/2026/documentation/compatibility-and-support/supported-models.html

**Decision candidate:** keep as `BENCHMARK / ADOPT ONLY IF NEEDED`; do not add OpenVINO to the runtime unless the simpler MediaPipe path fails the human acceptance gate.

## 4. New canonical evidence modality

Add:

```text
ATTENTION
```

to `EvidenceModality`.

The provider returns normal JARVIS-owned `IdentityEvidence`; it does not mutate trust or authority directly.

Conceptual provider result:

```python
AttentionVerdict = Literal[
    "ATTENTIVE",
    "NOT_ATTENTIVE",
    "AMBIGUOUS",
    "INSUFFICIENT_QUALITY",
]
```

Required binding fields:

- `session_id`
- `visual_track_id`
- `observed_at_monotonic`
- `expires_at_monotonic`
- `provider_id`
- `model_id`
- `quality`
- `verdict`
- `reason_codes`

Raw gaze vectors, iris coordinates, eye crops, and per-frame biometric geometry are transient implementation details and are not canonical audit state.

## 5. Attention semantics

Attention is intentionally **very short lived**.

Initial maximum age:

| Evidence | Initial maximum age | Condition |
| --- | ---: | --- |
| `ATTENTION` | 1.5 s | same OWNER visual track and usable eye visibility |

The provider should require a short temporal window rather than one frame. The exact frame count/duration is benchmarked locally.

Attention immediately becomes invalid when:

- the owner track is lost or changes;
- the face/eyes become insufficiently visible;
- the user looks away beyond the calibrated tolerance;
- eyes are closed beyond blink tolerance;
- the camera/provider becomes unavailable;
- Windows security/session invalidation clears the identity session.

A normal blink must not cause oscillating authority state. A deliberately closed-eye or sustained-look-away state must fail the attention predicate.

## 6. Trust model amendment

### T0 / T1

No change.

### T2 `CORROBORATED_OWNER`

T2 continues to mean that JARVIS has a fresh, corroborated owner hypothesis. T2 should **not disappear merely because the owner briefly looks away**; identity and attention are separate concepts.

The initial T2 evidence remains:

- expected active/unlocked Windows session;
- fresh OWNER face match on one stable visual track;
- recent randomized liveness success on that same track;
- no unresolved identity/association ambiguity;
- valid freshness and continuity.

Speaker identity may corroborate but cannot create T2 alone.

### New `OWNER_ATTENTIVE` predicate

Define a deterministic derived predicate:

```text
OWNER_ATTENTIVE =
    trust >= T2
    AND fresh ATTENTION == ATTENTIVE
    AND ATTENTION.visual_track_id == owner_visual_track_id
    AND no relevant subject-association ambiguity
```

This is not a new trust tier. It is a transient interaction predicate used by policy/approval rules.

### T3 `VERIFIED_OWNER`

No weakening. Windows Hello / future WebAuthn-FIDO2 remains the strong verifier.

A fresh successful T3 verification may satisfy the immediate interaction-intent requirement for the exact protected action that triggered it, but it still does not become a reusable blanket permission.

## 7. Authority and approval amendment

### R0 `ROUTINE`

No attention requirement. JARVIS can wake and converse normally even when no owner is looking at it.

### R1 `PRIVATE_READ`

Before speaking/displaying owner-private content through the ambient camera/voice path, require:

```text
T2 + OWNER_ATTENTIVE
```

unless the exact interaction has just completed T3 strong verification.

If the owner is recognized but looking away, JARVIS may state that private information is ready but should not disclose the sensitive payload until attention or strong verification is established.

### R2 `REVERSIBLE_LOCAL_CHANGE`

Direct low-impact non-private commands do not require gaze merely for convenience. Inferred/proactive changes may require attention or explicit confirmation according to policy.

### R3 `PERSISTENT_OR_EXTERNAL`

Spoken approval is valid only when all of the following are simultaneously true:

```text
exact ActionProposal is pending
AND trust >= T2
AND OWNER_ATTENTIVE
AND speaking actor association is unambiguous
AND approval text is accepted by the deterministic approval parser
AND receipt is fresh and one-time
```

If attention is absent/ambiguous, or the speaking actor cannot be bound safely, spoken consequential approval fails closed and escalates to `StrongVerifier` when policy permits.

This specifically prevents the case where the owner remains visible in frame while looking elsewhere and another person, a TV, or an unintended utterance supplies "yes".

### R4 `CRITICAL`

No change: exact proposal + T3 `StrongVerifier` is mandatory. RGB gaze/attention never replaces Windows Hello/FIDO2.

### R5 `RESTRICTED_DEV_ONLY`

No change.

## 8. Attempt throttling and fallback

Borrow the **fallback principle** from Face ID, not Apple's exact security claim.

JARVIS must distinguish passive non-attention from an explicit failed biometric elevation attempt:

- simply looking away does **not** increment a failure counter;
- an unknown passer-by does **not** lock the owner out;
- only a policy-triggered/user-engaged liveness/owner-elevation ceremony tied to an OWNER candidate can count as a failed attempt.

Initial policy candidate:

```text
5 consecutive explicit ambient biometric-elevation failures
    -> suspend ambient T2 elevation attempts
    -> require Windows Hello to reset/elevate
    -> apply bounded cooldown before ambient retry
```

The exact cooldown is implementation policy and will be calibrated during human testing. A successful strong verification resets the explicit-failure counter. The system must never respond to repeated failures by lowering requirements.

## 9. New threat-model requirements

The existing STRIDE/LINDDUN model is extended with these cases:

| ID | Threat | Required behavior |
| --- | --- | --- |
| S-ATT-01 | OWNER face visible but eyes closed/asleep | `ATTENTION` must not pass; no private disclosure/spoken consequential approval |
| S-ATT-02 | OWNER visible but looking elsewhere | OWNER identity may remain T2; `OWNER_ATTENTIVE` fails |
| S-ATT-03 | Static photo facing camera | attention alone is insufficient; randomized liveness + continuity still required for T2 |
| S-ATT-04 | Pre-recorded video looking at camera | attention alone is insufficient; fresh randomized challenge prevents ordinary replay from creating T2 |
| S-ATT-05 | Another person speaks while attentive OWNER is visible | spoken approval requires actor association; otherwise escalate/deny |
| S-ATT-06 | Sunglasses/occlusion prevent reliable eye state | verdict becomes `AMBIGUOUS`/`INSUFFICIENT_QUALITY`, never guessed attentive |
| S-ATT-07 | Virtual/injected camera feed fabricates gaze/liveness | ambient evidence remains non-root-of-trust; R4 still requires Windows Hello/FIDO2 |
| E-ATT-01 | LLM claims user is looking/approved | ignored unless deterministic provider + approval state produced valid evidence/receipt |
| I-ATT-01 | Gaze history becomes behavioral surveillance | no persistent gaze vectors/eye crops/attention timeline; audit only minimal reason codes |

## 10. Privacy rules

Attention processing must remain local and ephemeral.

Production path must not persist:

- raw eye crops;
- iris landmark coordinates;
- gaze vectors;
- per-frame eye-open scores;
- a timeline of where the owner looked;
- emotion, fatigue, interest, or psychological inferences.

Audit may record only what is required to explain a protected decision, for example:

- `ATTENTION_REQUIRED`
- `ATTENTION_PRESENT`
- `ATTENTION_ABSENT`
- `ATTENTION_AMBIGUOUS`
- provider/model/version
- timestamp/session/proposal binding

The amendment explicitly rejects converting eye tracking into general behavioral monitoring.

## 11. Validation gates

Before the attention path can be human-accepted:

1. **Attentive-owner trials:** at least 30 real Pocket-3 trials across normal lighting/position; target >=95% correct `ATTENTIVE` classification after calibration.
2. **Look-away trials:** at least 30 trials with OWNER visible but clearly looking away; target 0 protected disclosures/approvals accepted during the test set.
3. **Eyes-closed trials:** at least 20 sustained eyes-closed trials; target 0 `OWNER_ATTENTIVE` passes.
4. **Normal blink tolerance:** ordinary blinks must not cause repeated user-visible lock/unlock oscillation.
5. **Glasses/occlusion:** ordinary clear glasses are tested; unreliable sunglasses/occlusion must degrade to ambiguous rather than false attentive.
6. **Replay:** photo and ordinary prerecorded-video tests must never produce authority by attention alone and must still be blocked by T2 liveness/continuity rules.
7. **Multi-person:** an attentive owner remaining visible while another person says "yes" must not produce a valid R3 approval without verified actor association.
8. **Privacy:** tests confirm no raw eye crop, iris landmarks, gaze vector, or attention history appears in SQLite audit, ordinary logs, or crash-safe diagnostic fixtures.
9. **Resource cost:** benchmark the reused MediaPipe path on the real PC while RF-DETR tracking and realtime voice are active. The attention feature must not destabilize accepted voice/vision latency.
10. **Fallback comparison:** if MediaPipe cannot meet the above separation/reliability gates, benchmark OpenVINO `gaze-estimation-adas-0002` behind the same interface before changing architecture.

These are local acceptance gates, not claims of statistical biometric certification or Face-ID-equivalent false-match performance.

## 12. Implementation impact

After human approval, implementation order becomes:

1. Add `ATTENTION` to canonical evidence types and reason codes.
2. Add deterministic `OWNER_ATTENTIVE` derivation and unit tests before connecting a model.
3. Add policy/approval tests proving R1 disclosure and R3 spoken approval fail without fresh attention where required.
4. Implement `AttentionEvidenceProvider` using the already-selected head/face crop and MediaPipe Face Landmarker.
5. Calibrate on Pocket 3 real-human trials.
6. Add explicit biometric-attempt throttling and Windows-Hello escalation.
7. Run replay, look-away, eyes-closed, multi-person, privacy, latency, and degraded-mode acceptance tests.
8. Only benchmark/add OpenVINO gaze estimation if MediaPipe fails the defined gate.

## 13. Final amendment decision

**ADOPT** the Apple-inspired concept of attention-aware intent confirmation.  
**WRAP** attention behind JARVIS-owned typed evidence and deterministic policy.  
**ADOPT first** the existing MediaPipe Face Landmarker path to minimize dependency/runtime complexity.  
**BENCHMARK** OpenVINO gaze estimation only if necessary.  
**REJECT** any claim that Pocket-3 RGB eye tracking is Face ID, iris authentication, or a replacement for Windows Hello/FIDO2.

With this amendment, Step 3 keeps the original security architecture while making protected voice interaction behave more naturally: JARVIS may recognize that the owner is present continuously, but only treats the owner as actively engaging when fresh same-track attention evidence exists.
