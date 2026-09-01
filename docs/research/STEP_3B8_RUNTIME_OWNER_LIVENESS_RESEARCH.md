# Step 3B.8 — Runtime OWNER Identity + Liveness Binding Research

Date: 2026-08-30

## Status

**RESEARCH COMPLETE FOR EVIDENCE-ONLY INTEGRATION — IMPLEMENTATION NEXT — T2 MUST REMAIN DISABLED**

## Goal

Bind the already accepted OWNER face enrollment and liveness primitives to the same stable visual subject at runtime without prematurely claiming an authoritative OWNER-vs-UNKNOWN threshold.

The integrated slice must answer two independent questions:

1. does the current face look sufficiently similar to the encrypted enrolled OWNER template?
2. is that same visual subject currently supported as live rather than a presentation attack?

Neither answer is execution permission.

## Reuse rather than rebuild

3B.8 must reuse accepted components:

- Step-2.5 Pocket-3 camera, RF-DETR, persistent visual track, explicit target selection, BlazeFace head association, and `HeadFirstFramingPolicy`;
- YuNet + SFace pinned model/cache boundary;
- encrypted `SqliteOwnerProfileStore` + Windows DPAPI key protector;
- deterministic `sface-prototype-set-v1` OWNER template;
- MiniFASNet V1SE + V2 passive PAD provider;
- `TemporalPassiveLiveness` 15-observation fusion;
- 3B.7A randomized active liveness as uncertainty fallback;
- Windows WTS session state.

No parallel face scanner, identity database, liveness state machine, or authority mechanism should be introduced.

## Identity-threshold constraint

JARVIS still lacks a consenting live non-owner calibration dataset. Therefore 3B.8 must not promote a positive-only threshold into authoritative OWNER recognition.

OpenCV Zoo's SFace reference implementation uses cosine similarity `0.363` as its reference same-identity decision threshold. That value is useful as an external reference but is not accepted as a JARVIS OWNER threshold because camera, crop, enrollment, prototype selection, and deployment conditions differ.

The existing OWNER-positive calibration produced held-out genuine-owner scores with approximately:

- minimum `0.5659`;
- p01 `0.5771`;
- p05 `0.6410`;
- median `0.8072`.

The real enrollment produced an 8-prototype set, and runtime matching will use the maximum cosine similarity to those prototypes rather than a single centroid.

## Provisional evidence-only identity band

For 3B.8 diagnostic integration, use a deliberately conservative temporal tri-state rule over 15 fresh observations:

```text
median max-prototype cosine >= 0.65 → OWNER_CANDIDATE
median max-prototype cosine <= 0.35 → UNKNOWN
otherwise                            → AMBIGUOUS
<15 fresh observations               → INSUFFICIENT
```

Rationale:

- `0.65` sits just above the previous OWNER-positive p05 and is intentionally stricter than the positive tail rather than lowering the floor to make the OWNER always pass;
- `0.35` sits below the OpenCV SFace reference same-identity threshold (`0.363`) and therefore reserves UNKNOWN for very weak similarity;
- the broad middle band prevents JARVIS from pretending that an unvalidated impostor region is known;
- the result is evidence-only and cannot contribute to T2 until live non-owner separation is later calibrated and accepted.

This is a provisional integration band, not a production biometric threshold.

## Temporal identity behavior

Identity fusion should mirror the safety properties of passive liveness:

- 15 observations;
- same Windows session;
- same visual track;
- same SFace provider/model compatibility;
- gap > `0.50 s` clears the identity window;
- cross-session/track/provider observations are rejected;
- a short identity evidence TTL prevents stale presence from being reused.

Single-frame SFace matches remain non-authoritative.

## Template compatibility

Before runtime recognition, the decrypted face template metadata must match the currently loaded recognizer boundary:

- modality = face;
- template format = `sface-prototype-set-v1`;
- provider = `opencv-sface-prototype-set-v1`;
- exact current SFace model id/source revision/SHA-256;
- expected embedding dimension;
- enrollment compatibility version.

Mismatch fails closed; JARVIS must not silently compare embeddings produced by incompatible model generations.

## Same-track binding

The critical 3B.8 invariant is:

```text
same active Windows session
+ same stable visual track
+ associated face/head
        ├── SFace identity observations
        └── MiniFAS liveness observations
```

Identity and liveness observations from different tracks must never be combined.

If track association changes or the selected track is lost long enough to break freshness, both temporal windows reset.

## Integrated assessment vocabulary

Keep identity and liveness independent:

Identity:

- `INSUFFICIENT`
- `OWNER_CANDIDATE`
- `AMBIGUOUS`
- `UNKNOWN`

Liveness:

- `INSUFFICIENT`
- `LIVE`
- `UNCERTAIN`
- `SPOOF`

Integrated candidate interpretation:

```text
OWNER_CANDIDATE + LIVE      → LIVE_OWNER_CANDIDATE
OWNER_CANDIDATE + UNCERTAIN → ACTIVE_CHALLENGE_ELIGIBLE
OWNER_CANDIDATE + SPOOF     → SPOOFED_OWNER_PRESENTATION
UNKNOWN + any liveness      → UNKNOWN_SUBJECT
AMBIGUOUS + any liveness    → AMBIGUOUS_SUBJECT
anything insufficient       → INSUFFICIENT
```

`LIVE_OWNER_CANDIDATE` is deliberately not `T2 CORROBORATED_OWNER`.

## Evidence mapping

For integration testing only:

- `OWNER_CANDIDATE` may map to typed `FACE_MATCH/MATCH` evidence with an explicit reason code that the threshold is provisional and T2-disabled;
- `UNKNOWN` maps to `FACE_MATCH/NO_MATCH`;
- `AMBIGUOUS` and `INSUFFICIENT` map to `FACE_MATCH/INSUFFICIENT`;
- passive liveness continues to map to `FACE_LIVENESS` evidence through its accepted contract.

Downstream trust composition must ignore these new face-match results for T2 until 3B.8 is human-accepted and the later T2 composition slice is explicitly approved.

## Active challenge fallback

Only `OWNER_CANDIDATE + UNCERTAIN` is eligible to request active liveness when liveness is actually required by the trust/risk path.

Do not challenge:

- a clear `SPOOF` automatically;
- an `UNKNOWN` person in order to turn them into OWNER;
- an `AMBIGUOUS` identity merely because they can perform a liveness action.

Liveness cannot repair weak identity evidence.

## Privacy

The integrated harness/runtime must not persist:

- camera frames;
- aligned face crops;
- SFace embeddings;
- MiniFAS input/output tensors;
- landmark/blendshape vectors.

The only persistent biometric material remains the encrypted enrolled OWNER prototype set.

Derived scalar diagnostics may be printed during acceptance but are not authority state by themselves.

## Real-machine acceptance target

3B.8 acceptance should include:

1. real OWNER normal-use run → `LIVE_OWNER_CANDIDATE` should be stable;
2. OWNER static phone photo → identity may look OWNER-like but liveness must produce `SPOOF`;
3. OWNER prerecorded phone video → identity may look OWNER-like but liveness must produce `SPOOF`;
4. track loss/reselection → both temporal windows reset;
5. Windows lock/session change → evidence invalidates/fails closed;
6. model/template compatibility mismatch → fail closed;
7. no raw biometric persistence;
8. `face_evidence_grants_T2 = False` throughout.

A consenting live non-owner test remains a later requirement before an authoritative OWNER-vs-UNKNOWN threshold can participate in T2.

## Future change

When depth/IR hardware is adopted, replace or strengthen the liveness provider without changing the identity threshold semantics, session/track binding, evidence contracts, or action-authority architecture.
