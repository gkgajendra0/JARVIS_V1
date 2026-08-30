# Step 3B.8 — OWNER + Liveness Real-Machine Acceptance Results

Date: 2026-08-30

## Status

**HUMAN ACCEPTANCE IN PROGRESS — LIVE OWNER SUBTEST PASSED — T2 REMAINS DISABLED**

This document records real Windows + DJI Pocket 3 acceptance evidence for the Step 3B.8 integrated OWNER identity + passive liveness path.

The harness is evidence-only. No result in this document grants T2 authority.

## Subtest 1 — live OWNER normal-use

Command:

```powershell
jarvis-owner-evidence-live --scenario live
```

Result:

```text
scenario = live
windows_session = wts:3
valid_integrated_observations = 300
associated_head_attempts = 361

max_prototype_cosine:
  n = 300
  min = 0.6128
  p05 = 0.6816
  median = 0.7982
  p95 = 0.8435
  max = 0.8779

minifas_real_probability:
  n = 300
  min = 0.9842
  p05 = 0.9974
  median = 0.9998
  p95 = 0.9999
  max = 1.0000

identity_state_counts = {'insufficient': 28, 'owner_candidate': 272}
liveness_state_counts = {'insufficient': 28, 'live': 272}
combined_state_counts = {'insufficient': 28, 'live_owner_candidate': 272}
session_invalidated = False

frames_saved = False
aligned_faces_saved = False
sface_embeddings_saved = False
pad_tensors_saved = False
pad_output_vectors_saved = False
identity_threshold_authoritative = False
live_non_owner_calibration_available = False
face_evidence_grants_T2 = False
STEP_3B8_OWNER_LIVENESS_EVIDENCE = COMPLETE
```

### Interpretation

PASS for the live-OWNER subtest.

- The encrypted enrolled 8-prototype OWNER template loaded successfully and was compatible with the pinned SFace runtime.
- Genuine live OWNER temporal identity reached `OWNER_CANDIDATE` for 272 of 300 integrated observations after temporal warm-up/reset periods.
- Passive MiniFAS liveness reached `LIVE` for the same 272 observations.
- The combined same-session/same-track assessment reached `LIVE_OWNER_CANDIDATE` for the same 272 observations.
- No session invalidation occurred.
- No raw frames, aligned faces, SFace embeddings, PAD tensors, or PAD output vectors were persisted.
- `face_evidence_grants_T2 = False` remained intact.

The 28 `INSUFFICIENT` observations are exactly consistent with two 14-observation temporal warm-up periods. Because both identity and liveness show the same count, this is consistent with one shared freshness-gap reset after the initial warm-up. The current harness does not print an explicit temporal-reset counter, so that reset explanation is an inference from the counts rather than a directly logged event. The fail-closed behavior itself is acceptable; repeated resets in later runs should be monitored for runtime UX impact.

### Threshold note

The live run supports the provisional OWNER-candidate integration floor but does not make it authoritative. The genuine run had:

- raw minimum max-prototype cosine `0.6128`, below the provisional `0.65` temporal OWNER-candidate floor;
- p05 `0.6816` and median `0.7982`;
- temporal fusion nevertheless produced stable `OWNER_CANDIDATE` after valid windows filled.

A consenting live non-owner calibration remains required before OWNER-vs-UNKNOWN thresholds may participate in T2.

## Remaining 3B.8 human acceptance subtests

1. phone-photo OWNER presentation on the same stable person track → liveness must fail closed as `SPOOF` / `SPOOFED_OWNER_PRESENTATION` when identity is OWNER-like;
2. prerecorded phone-video OWNER presentation on the same stable person track → liveness must fail closed;
3. target loss/reselection → temporal identity and liveness windows must reset;
4. Windows lock/session transition → evidence must invalidate and harness must fail closed;
5. T2 must remain disabled throughout.

Full Step 3B.8 human acceptance is not yet claimed.
